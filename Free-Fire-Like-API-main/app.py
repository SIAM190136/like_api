import os
import json
import base64
import binascii
import asyncio
import warnings
from datetime import datetime

from flask import Flask, request, jsonify
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
from google.protobuf.message import DecodeError
import aiohttp
import requests

import like_pb2
import like_count_pb2
import uid_generator_pb2

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

app = Flask(__name__)

# ---- OB55 constants ----
AES_KEY = b"Yg&tc%DEuh6%Zc^8"
AES_IV  = b"6oyZDr22E3ychjM%"

HOST_IND = "https://client.ind.freefiremobile.com"
HOST_US  = "https://client.us.freefiremobile.com"
HOST_BP  = "https://clientbp.ppmainecoonghj.com"   # BD / SG / TH / VN / ID / MY / PH / ME

RELEASE_VERSION = "OB55"

HEADERS = {
    "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
    "Connection": "Keep-Alive",
    "Accept-Encoding": "gzip",
    "X-GA-SV": "1789638359",
    "Content-Type": "application/x-www-form-urlencoded",
    "Expect": "100-continue",
    "X-Unity-Version": "2018.4.12f1",
    "X-GA": "v1 1",
    "ReleaseVersion": RELEASE_VERSION,
}

# ---------------- helpers ----------------
def load_tokens():
    try:
        with open("tokens.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            return None
        return data
    except Exception as e:
        app.logger.error(f"tokens.json load error: {e}")
        return None


def encrypt_message(plaintext: bytes) -> str | None:
    try:
        cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode()
    except Exception as e:
        app.logger.error(f"encrypt error: {e}")
        return None


def make_like_payload(uid: int, region: str) -> bytes | None:
    try:
        msg = like_pb2.like()
        msg.uid = int(uid)
        msg.region = region
        return msg.SerializeToString()
    except Exception as e:
        app.logger.error(f"like payload error: {e}")
        return None


def make_uid_payload(uid: int) -> bytes | None:
    try:
        msg = uid_generator_pb2.uid_generator()
        msg.saturn_ = int(uid)
        msg.garena = 1
        return msg.SerializeToString()
    except Exception as e:
        app.logger.error(f"uid payload error: {e}")
        return None


def enc(uid: int) -> str | None:
    raw = make_uid_payload(uid)
    if raw is None:
        return None
    return encrypt_message(raw)


def host_for(region: str) -> str:
    if region == "IND":
        return HOST_IND
    if region in {"BR", "US", "SAC", "NA"}:
        return HOST_US
    return HOST_BP


def decode_info(binary: bytes):
    try:
        obj = like_count_pb2.Info()
        obj.ParseFromString(binary)
        return obj
    except DecodeError as e:
        app.logger.error(f"decode error: {e}")
        return None
    except Exception as e:
        app.logger.error(f"decode unexpected: {e}")
        return None


def fetch_info(encrypted_uid: str, region: str, token: str):
    url = f"{host_for(region)}/GetPlayerPersonalShow"
    try:
        r = requests.post(
            url,
            data=bytes.fromhex(encrypted_uid),
            headers={**HEADERS, "Authorization": f"Bearer {token}"},
            verify=False,
            timeout=25,
        )
        if r.status_code != 200:
            app.logger.error(f"GetPlayerPersonalShow {r.status_code}")
            return None
        return decode_info(r.content)
    except Exception as e:
        app.logger.error(f"fetch_info: {e}")
        return None


# ---------------- async like sender ----------------
async def _post_like(session, url, data, token):
    try:
        async with session.post(
            url,
            data=data,
            headers={**HEADERS, "Authorization": f"Bearer {token}"},
        ) as resp:
            if resp.status != 200:
                return resp.status
            return await resp.text()
    except Exception as e:
        app.logger.error(f"_post_like: {e}")
        return None


async def send_likes(uid: int, region: str, url: str, tokens: list, count: int = 100):
    raw = make_like_payload(uid, region)
    if raw is None:
        return None
    encrypted = encrypt_message(raw)
    if encrypted is None:
        return None
    payload = bytes.fromhex(encrypted)

    async with aiohttp.ClientSession() as session:
        tasks = [
            _post_like(session, url, payload, tokens[i % len(tokens)]["token"])
            for i in range(count)
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)


def run_likes(uid, region, url, tokens, count=100):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(send_likes(uid, region, url, tokens, count))
    finally:
        loop.close()


# ---------------- routes ----------------
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "credit": "https://t.me/paglu_dev",
        "message": "Free Fire Like API — OB55 / BD ready",
        "status": "running",
        "ob": RELEASE_VERSION,
        "endpoint": "/like?uid=<uid>&server_name=BD",
    })


@app.route("/like", methods=["GET"])
def handle_like():
    uid = request.args.get("uid", "").strip()
    if not uid.isdigit():
        return jsonify({"error": "uid required (numeric)"}), 400

    tokens = load_tokens()
    if not tokens:
        return jsonify({"error": "tokens.json missing/empty — run update_tokens.py"}), 500

    token = tokens[0]["token"]

    region = request.args.get("server_name", "").upper()
    if not region:
        try:
            body = token.split(".")[1]
            body += "=" * (-len(body) % 4)
            claims = json.loads(base64.urlsafe_b64decode(body).decode())
            region = claims.get("lock_region", "").upper()
        except Exception as e:
            app.logger.error(f"token decode: {e}")

    if not region:
        return jsonify({"error": "server_name missing and token has no lock_region"}), 400

    encrypted_uid = enc(uid)
    if encrypted_uid is None:
        return jsonify({"error": "encryption failed"}), 500

    before_obj = fetch_info(encrypted_uid, region, token)
    if before_obj is None:
        return jsonify({"error": "cannot read player — token probably dead"}), 500

    before_json = json.loads(MessageToJson(before_obj))
    before_likes = int(before_json.get("AccountInfo", {}).get("Likes", 0) or 0)

    like_url = f"{host_for(region)}/LikeProfile"
    run_likes(uid, region, like_url, tokens, 100)

    after_obj = fetch_info(encrypted_uid, region, token)
    if after_obj is None:
        return jsonify({"error": "cannot read player after likes"}), 500

    after_json = json.loads(MessageToJson(after_obj))
    info = after_json.get("AccountInfo", {})
    after_likes = int(info.get("Likes", 0) or 0)
    nick = str(info.get("PlayerNickname", ""))
    pid = int(info.get("UID", 0) or 0)

    given = after_likes - before_likes

    return jsonify({
        "credit": "https://t.me/paglu_dev",
        "LikesGivenByAPI": given,
        "LikesafterCommand": after_likes,
        "LikesbeforeCommand": before_likes,
        "PlayerNickname": nick,
        "Region": region,
        "UID": pid,
        "status": 1 if given > 0 else 2,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)