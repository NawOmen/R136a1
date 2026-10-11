"""Destructive restore guards must fail before any Docker mutation."""
import argparse
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import json

spec=importlib.util.spec_from_file_location('operations',Path(__file__).with_name('operations.py'))
ops=importlib.util.module_from_spec(spec);spec.loader.exec_module(ops)

class RestoreSafety(unittest.TestCase):
    def test_rejects_traversal_links_and_devices(self):
        for name,kind in [('../escape',tarfile.REGTYPE),('/escape',tarfile.REGTYPE),('link',tarfile.SYMTYPE),('device',tarfile.CHRTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'minio.tar'
                with tarfile.open(path,'w') as archive:
                    item=tarfile.TarInfo(name);item.type=kind;item.size=0
                    archive.addfile(item,io.BytesIO())
                with self.assertRaises(ValueError):ops.validate_archive(path)

    def test_same_project_or_existing_container_cannot_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'manifest.json').write_text(json.dumps({'format':1,'source_project':'source','files':{'postgres.dump':'','minio.tar':''}}))
            for project,existing in [('source',[]),('separate',[{}])]:
                with self.subTest(project=project),patch.object(ops,'containers',return_value=existing),patch.object(ops,'run') as mutation:
                    with self.assertRaises(ValueError):ops.restore(argparse.Namespace(directory=path,project=project))
                    mutation.assert_not_called()

    def test_corrupt_dump_cannot_create_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'postgres.dump').write_bytes(b'changed')
            (path/'manifest.json').write_text(json.dumps({'format':1,'source_project':'source','files':{'postgres.dump':'invalid','minio.tar':'invalid'}}))
            with patch.object(ops,'containers',return_value=[]),patch.object(ops,'run') as mutation:
                with self.assertRaises(ValueError):ops.restore(argparse.Namespace(directory=path,project='separate'))
                mutation.assert_not_called()

    def test_existing_volume_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'postgres.dump').write_bytes(b'archive')
            with tarfile.open(path/'minio.tar','w'):pass
            (path/'manifest.json').write_text(json.dumps({'format':1,'source_project':'source',
                'files':{name:ops.digest(path/name) for name in ('postgres.dump','minio.tar')}}))
            with patch.object(ops,'containers',return_value=[]),patch.object(ops,'output',return_value='target_postgres_data'),patch.object(ops,'run') as mutation:
                with self.assertRaises(ValueError):ops.restore(argparse.Namespace(directory=path,project='target'))
                mutation.assert_not_called()

    def test_dirty_checkout_cannot_claim_head_version(self):
        from types import SimpleNamespace
        with patch.object(ops.subprocess,'run',return_value=SimpleNamespace(returncode=1)),patch.object(ops,'containers') as read,patch.object(ops,'run') as mutation:
            with self.assertRaises(ValueError):ops.backup(argparse.Namespace(project='source',directory=Path('/tmp/unused')))
            read.assert_not_called();mutation.assert_not_called()

    def test_bound_source_revision_does_not_relabel_image(self):
        container={'Config':{'Labels':{'com.docker.compose.service':'marketplace'}},'Image':'sha256:old',
                   'Mounts':[{'Type':'bind','Destination':'/app','Source':str(ops.ROOT/'services/marketplace')}]}
        with patch.object(ops,'inspect',return_value={'Config':{'Labels':{'org.opencontainers.image.revision':'old-commit'}}}):
            version=ops.application_versions([container],'current-commit')['marketplace']
            self.assertEqual(version,{'image_revision':'old-commit','bound_source_revision':'current-commit'})


if __name__=='__main__':unittest.main()
