"""Tests fuer den Asset-Inspector mit einem simulierten Roblox-Client.

Der echte Client spricht mit Roblox; hier wird nur die Verarbeitung geprueft:
Lizenz-Entscheidung, Modellvermessung, Kontaktabzug und Bericht.
"""
from __future__ import annotations

import importlib
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

open_cloud = importlib.import_module("1_system.roblox_api.open_cloud")
inspector = importlib.import_module("1_system.roblox_api.asset_inspector")
test_rbxm = importlib.import_module("tests.test_rbxm")


class FakeClient:
    """Minimaler Ersatz fuer RobloxClient mit zwei Assets im Gepaeck."""

    def __init__(self, assets=None):
        self.assets = assets or {
            1001: open_cloud.AssetInfo(asset_id=1001, name="Holzlaterne",
                                       asset_type_id=10, creator="Studio", creator_id=4711),
            1002: open_cloud.AssetInfo(asset_id=1002, name="Nike Cap",
                                       asset_type_id=8, creator="Fan", creator_id=99),
        }
        self.downloads = 0

    def asset_info(self, asset_id: int):
        return self.assets[int(asset_id)]

    def download_thumbnail(self, asset_id: int, target: Path, size: str = "420x420"):
        from PIL import Image

        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (420, 420), "#2f6f8f")
        image.save(target)
        return target

    def download_asset(self, asset_id: int, target: Path, force: bool = False, expected=None):
        target = Path(target).with_suffix(".rbxm")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(test_rbxm.build_rbxm())
        self.downloads += 1
        return target

    def threed_thumbnail(self, asset_id, target):
        return None


def test_inspect_asset_neutral(tmp_path):
    client = FakeClient()
    report = inspector.inspect_asset(client, 1001, tmp_path)
    assert report.name == "Holzlaterne"
    assert report.license_ok is True
    assert report.parts == 2
    assert report.size_studs[0] == pytest.approx(4.0, abs=0.05)
    assert 0.05 <= report.suggested_scale <= 20
    assert report.thumbnail and Path(report.thumbnail).is_file()
    assert report.asset_type == "Model"


def test_inspect_asset_brand_is_blocked(tmp_path):
    client = FakeClient()
    report = inspector.inspect_asset(client, 1002, tmp_path)
    assert report.license_ok is False
    assert "nike" in report.license_note.lower()


def test_contact_sheet_and_report(tmp_path):
    client = FakeClient()
    reports = [inspector.inspect_asset(client, asset_id, tmp_path) for asset_id in (1001, 1002)]
    sheet = inspector.build_contact_sheet(reports, tmp_path / "kontakt.png")
    assert sheet is not None and sheet.is_file()
    report_path = inspector.write_report(reports, tmp_path, sheet)
    text = report_path.read_text(encoding="utf-8")
    assert "Holzlaterne" in text and "PRUEFEN" in text
    assert "![Kontaktabzug](kontakt.png)" in text


def test_inspect_many(tmp_path):
    reports, report_path, sheet = inspector.inspect_many(
        [1001, 1002], tmp_path, client=FakeClient())
    assert len(reports) == 2
    assert report_path.is_file() and sheet.is_file()


def test_analyze_model_scales_to_three_studs():
    model = test_rbxm.rbxm.RbxmParser().parse_bytes(test_rbxm.build_rbxm())
    size, scale = inspector.analyze_model(model)
    largest = max(size)
    assert scale == pytest.approx(min(max(3.0 / largest, 0.05), 20.0), abs=1e-6)


def test_slot_for_type_mapping():
    assert inspector.SLOT_FOR_TYPE["Hat"] == "HatAttachment"
    assert inspector.SLOT_FOR_TYPE["HairAccessory"] == "HairAttachment"


def test_prepare_asset_neutral(tmp_path):
    prepare = importlib.import_module("1_system.roblox_api.prepare_assets")
    result = prepare.prepare_asset(FakeClient(), 1001, tmp_path, convert=False)
    assert result["license_ok"] is True
    assert result["parts"] == 2
    assert result["slot"] == "HatAttachment"
    assert Path(result["raw"]).is_file()
    assert result["scale"] > 0


def test_prepare_asset_brand_is_flagged(tmp_path):
    prepare = importlib.import_module("1_system.roblox_api.prepare_assets")
    result = prepare.prepare_asset(FakeClient(), 1002, tmp_path, convert=False)
    assert result["license_ok"] is False
    assert result["slot"] == "HatAttachment"


def test_creator_store_search_uses_documented_post_contract(tmp_path, monkeypatch):
    client = open_cloud.RobloxClient(api_key='fake', cache_dir=tmp_path)
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        from types import SimpleNamespace
        return SimpleNamespace(json=lambda: {'creatorStoreAssets': [
            {'asset': {'id': 123, 'name': 'Street lamp', 'description': 'A lamp'},
             'creator': {'userId': 42, 'name': 'Artist'}}]})
    monkeypatch.setattr(client, '_request', request)
    results = client.search_creator_store('lamp', limit=3)
    assert results[0]['id'] == 123 and results[0]['creator_id'] == 42
    method, url, options = calls[0]
    assert method == 'POST' and url.endswith('/assets:search')
    assert options['json_body'] == {'query': 'lamp', 'maxPageSize': 3,
                                    'searchCategoryType': 'Model', 'maxPriceCents': 0}


def test_roblox_api_key_is_not_followed_on_redirect(tmp_path):
    from types import SimpleNamespace
    class Session:
        def __init__(self):
            self.headers = {}
            self.calls = []
        def request(self, method, url, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(status_code=302, headers={}, text='')
    session = Session()
    client = open_cloud.RobloxClient(api_key='fake-secret', cache_dir=tmp_path, session=session)
    with pytest.raises(open_cloud.RobloxApiError):
        client._request('GET', open_cloud.ASSET_DELIVERY + '/123')
    assert session.calls[0]['allow_redirects'] is False


def test_delivery_json_error_is_not_misreported_as_success(tmp_path, monkeypatch):
    from types import SimpleNamespace
    client = open_cloud.RobloxClient(api_key='fake', cache_dir=tmp_path)
    monkeypatch.setattr(client, '_request', lambda *a, **kw: SimpleNamespace(
        headers={'Content-Type': 'application/json'},
        json=lambda: {'errors': [{'code': 409, 'message': 'not usable'}]}))
    with pytest.raises(open_cloud.RobloxApiError, match='409'):
        client.asset_content(123)


def test_verify_checks_delivery_with_current_search_results(tmp_path, monkeypatch):
    client = open_cloud.RobloxClient(api_key='fake', cache_dir=tmp_path)
    monkeypatch.setattr(client, 'search_creator_store', lambda *a, **kw: [
        {'id': 10, 'name': 'first'}, {'id': 20, 'name': 'second'}])
    monkeypatch.setattr(client, 'asset_info', lambda _: object())
    monkeypatch.setattr(client, 'thumbnail_url', lambda _: 'https://example.test/image')
    calls = []
    def content(asset_id):
        calls.append(asset_id)
        if asset_id == 10:
            raise open_cloud.RobloxApiError('not available')
        return b'x' * 101, 'application/octet-stream'
    monkeypatch.setattr(client, 'asset_content', content)
    report = client.verify()
    assert report['search_ok'] and report['delivery_ok'] and not report['errors']
    assert calls == [10, 20]
