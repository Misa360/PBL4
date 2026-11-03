"""Filesystem and document contracts after separating the static frontend."""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from app.server import WEB

VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.assets, self.stack, self.errors = set(), [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            if attrs['id'] in self.ids:
                self.errors.append('Duplicate ID '+attrs['id'])
            self.ids.add(attrs['id'])
        if tag in ('script','link'):
            value = attrs.get('src') or attrs.get('href')
            if value and not urlsplit(value).scheme:
                self.assets.append(value)
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append('Unexpected closing '+tag)
        elif self.stack:
            self.stack.pop()


class WebStructureTests(unittest.TestCase):
    def test_documents_keep_controller_ids_and_local_assets(self):
        for page, controller in [('network.html','js/optimizer/app.js'),('index.html','js/optimizer/earth-optimizer.js')]:
            with self.subTest(page=page):
                document = Document()
                document.feed((WEB/page).read_text(encoding='utf-8'))
                self.assertEqual(document.errors, [])
                self.assertEqual(document.stack, [])
                for value in document.assets:
                    self.assertTrue((WEB/urlsplit(value).path).is_file(), value)
                source = (WEB/controller).read_text(encoding='utf-8')
                ids = set(re.findall(r"\$\('([^']+)'\)",source))
                self.assertFalse(ids-document.ids, ids-document.ids)

    def test_relative_module_imports_resolve_inside_web(self):
        for path in (WEB/'js').rglob('*.js'):
            source = path.read_text(encoding='utf-8')
            for relative in re.findall(r"(?:from\s+|import\s*)['\"](\.[^'\"]+)['\"]",source):
                target = (path.parent/relative).resolve()
                self.assertTrue(target.is_relative_to(WEB))
                self.assertTrue(target.is_file(),str(target))
