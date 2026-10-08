# -*- coding: utf-8 -*-
"""Тесты AllVPN: парсеры ключей, free-месяц, конфиг движка, x25519, WARP-профиль."""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from allvpn import keys, state, warp, engine, sources  # noqa: E402


# ------------------------------------------------------------------ state --

def test_free_month(tmp_path, monkeypatch):
    monkeypatch.setattr(state.config, "STATE_FILE", str(tmp_path / "s.json"))
    st = state.ensure_free(state.load())
    assert state.free_active(st)
    assert 28 <= state.days_left(st) <= 30
    # free не продлевается повторным запуском
    st2 = state.ensure_free(state.load())
    assert st2["free_until"] == st["free_until"]


# ------------------------------------------------------------------ keys --

VLESS = ("vless://11111111-2222-3333-4444-555555555555@1.2.3.4:443"
         "?security=reality&sni=example.com&fp=chrome&pbk=PUBKEY&sid=abcd"
         "&type=ws&path=%2Fws&host=example.com&flow=xtls-rprx-vision#МояНода")


def test_parse_vless_reality():
    n = keys.parse_any(VLESS)
    ob = n["outbound"]
    assert ob["type"] == "vless" and ob["server"] == "1.2.3.4" and ob["server_port"] == 443
    assert ob["flow"] == "xtls-rprx-vision"
    assert ob["tls"]["reality"] == {"enabled": True, "public_key": "PUBKEY", "short_id": "abcd"}
    assert ob["transport"]["type"] == "ws" and ob["transport"]["path"] == "/ws"
    assert n["name"] == "МояНода"


def test_parse_ss_legacy():
    raw = "aes-256-gcm:secretpass@5.6.7.8:8388#SSnode"
    uri = "ss://" + base64.b64encode(raw.encode()).decode()
    n = keys.parse_any(uri)
    ob = n["outbound"]
    assert ob["type"] == "shadowsocks" and ob["method"] == "aes-256-gcm"
    assert ob["password"] == "secretpass" and ob["server_port"] == 8388


def test_parse_vmess():
    payload = {"add": "9.9.9.9", "port": "443", "id": "uuid-x", "aid": "0",
               "net": "ws", "path": "/ray", "tls": "tls", "ps": "Vmess node"}
    uri = "vmess://" + base64.b64encode(json.dumps(payload).encode()).decode()
    n = keys.parse_any(uri)
    ob = n["outbound"]
    assert ob["type"] == "vmess" and ob["transport"]["type"] == "ws"
    assert ob["tls"]["enabled"] and n["name"] == "Vmess node"


def test_parse_wg_conf():
    conf = (open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "key", "WARPv3_79.conf"), encoding="utf-8").read()
            if os.path.isdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                          "key"))
            else None)
    if conf is None:
        conf = ("[Interface]\nPrivateKey = AAA=\nAddress = 172.16.0.2\nMTU = 1280\n"
                "Jc = 4\nJmin = 40\nJmax = 70\n\n[Peer]\nPublicKey = BBB=\n"
                "AllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = 1.1.1.1:2408\n")
    n = keys.parse_wg_conf(conf, "test")
    ob = n["outbound"]
    assert ob["type"] == "wireguard" and ob["server_port"] == 2408
    assert ob["peer_public_key"]


# ----------------------------------------------------------------- warp --

def test_x25519_rfc7748():
    k = int.from_bytes(bytes.fromhex(
        "a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4"), "little")
    u = int.from_bytes(bytes.fromhex(
        "e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c"), "little")
    out = warp._x25519(k, u).to_bytes(32, "little").hex()
    assert out == "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552"


def test_keypair_clamped():
    priv, pub = warp.gen_keypair()
    raw = base64.b64decode(priv)
    assert raw[0] & 7 == 0 and raw[31] & 128 == 0 and raw[31] & 64
    pub2 = warp._x25519(int.from_bytes(raw, "little"), 9).to_bytes(32, "little")
    assert base64.b64encode(pub2).decode() == pub


def test_profile_learning():
    model = warp.learn_profile()
    if not model.get("empty"):
        s = warp.sample_profile(model)
        assert "mtu" in s and "endpoint" in s


# ---------------------------------------------------------------- engine --

def test_build_config_valid():
    node = keys.make_node({"type": "shadowsocks", "tag": "s1", "server": "1.2.3.4",
                           "server_port": 8388, "method": "aes-256-gcm",
                           "password": "p"}, "s1", "free")
    node2 = keys.make_node({"type": "wireguard", "tag": "w1", "server": "1.1.1.1",
                            "server_port": 2408, "local_address": ["172.16.0.2/32"],
                            "private_key": "AAA=", "peer_public_key": "BBB=",
                            "amnezia": {"jc": 4}}, "w1", "own")
    cfg = engine.build_config([node, node2], "s1")
    assert cfg["outbounds"][0]["tag"] == "allvpn"
    assert "s1" in cfg["outbounds"][0]["outbounds"]
    ep = cfg["endpoints"][0]
    assert ep["type"] == "wireguard" and ep["peers"][0]["port"] == 2408
    assert "amnezia" not in ep and "amnezia" not in node2["outbound"]


def test_sources_load():
    data = sources.load_all()
    assert data["own"] or data["free"]
    for n in data["free"] + data["own"]:
        assert n["outbound"]["tag"]
        assert n["proto"] in sources.SUPPORTED_TYPES
