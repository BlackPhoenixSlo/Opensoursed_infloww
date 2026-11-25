from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import base64
import io

from PIL import Image

from _pre_enforcement import seed_pre_enforcement_install
from db.engine import get_session
from db.models import Account, User, UserAccount
import vault_settings

BASE = "/admin/vault-ai/category-icons"


def _login(username: str):
    client = _harness.make_client()
    response = client.post("/auth/login", json={"username": username, "password": "test password"})
    assert response.status_code == 200, response.text
    return client


async def case_upload_crop_share_within_agency_and_reset():
    async with get_session() as session:
        session.add_all([
            User(id="a-icons", username="agency_icons_a", password="test password"),
            User(id="b-icons", username="agency_icons_b", password="test password"),
            Account(id="creator-a1", nickname="Creator A1"),
            Account(id="creator-a2", nickname="Creator A2"),
            Account(id="creator-b1", nickname="Creator B1"),
        ])
    async with get_session() as session:
        session.add_all([
            UserAccount(user_id="a-icons", account_id="creator-a1"),
            UserAccount(user_id="a-icons", account_id="creator-a2"),
            UserAccount(user_id="b-icons", account_id="creator-b1"),
        ])
    await seed_pre_enforcement_install()
    owner = _login("agency_icons_a")
    other = _login("agency_icons_b")
    account = {"account_id": "creator-a1"}
    endpoint = BASE + "/covered-breast"
    with io.BytesIO() as output:
        image = Image.new("RGB", (120, 220), (10, 40, 220))
        image.paste((240, 20, 35), (0, 0, 120, 110))
        image.save(output, "PNG")
        files = {"file": ("picture.png", output.getvalue(), "image/png")}
    off = owner.get(BASE, params=account)
    assert off.status_code == 200 and off.json() == {"enabled": False, "can_edit": False, "icons": {}}, off.text
    assert owner.post(endpoint, params=account, data={"x": "0.5", "y": "0"}, files=files).status_code == 404
    assert owner.delete(endpoint, params=account).status_code == 404
    for aid in ("creator-a1", "creator-a2", "creator-b1"):
        await vault_settings.put(aid, standard_folders=True)
    response = owner.post(endpoint, params=account, data={"x": "0.5", "y": "0"}, files=files)
    assert response.status_code == 200, response.text
    shared = owner.get(BASE, params={"account_id": "creator-a2"})
    assert shared.status_code == 200, shared.text
    assert shared.headers["cache-control"] == "private, no-store"
    icon = shared.json()["icons"]["covered-breast"]
    with Image.open(io.BytesIO(base64.b64decode(icon))) as crop:
        assert crop.size == (192, 192) and crop.format == "WEBP"
        assert crop.getpixel((96, 96))[0] > 220, "Selected top region was not retained"
    assert other.get(BASE, params={"account_id": "creator-b1"}).json()["icons"] == {}
    assert other.get(BASE, params=account).status_code == 403
    assert other.delete(endpoint, params=account).status_code == 403
    bad_file = {"file": ("picture.png", b"invalid", "image/png")}
    assert owner.post(endpoint, params=account, files=bad_file).status_code == 400
    assert owner.get(BASE, params=account).json()["icons"]["covered-breast"] == icon
    assert owner.delete(endpoint, params=account).status_code == 200
    assert owner.get(BASE, params=account).json()["icons"] == {}
    assert owner.post(endpoint, params=account, data={"x": "0.5", "y": "0"}, files=files).status_code == 200
    await vault_settings.put("creator-a2", standard_folders=False)
    assert owner.get(BASE, params={"account_id": "creator-a2"}).json() == {"enabled": False, "can_edit": False, "icons": {}}
    assert "covered-breast" in owner.get(BASE, params=account).json()["icons"]
    assert _harness.make_client().get(BASE, params=account).status_code == 401


if __name__ == "__main__":
    _harness.run()
