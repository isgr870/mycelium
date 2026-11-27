#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DEFAULT_REG = Path(
    os.environ.get(
        "MYCELIUM_TRUST_REGISTRY",
        f"{os.environ.get('PREFIX', '')}/tmp/mycelium_stage/peers_trust.json",
    )
)


def load_reg(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"peers": {}}


def save_reg(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_keygen(args: argparse.Namespace) -> None:
    priv = Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    priv_raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")
    priv_b64 = base64.b64encode(priv_raw).decode("ascii")
    node_id = hashlib.sha256(pub_raw).hexdigest()[:24]
    print(json.dumps({
        "label": args.label,
        "node_id": node_id,
        "public_key_b64": pub_b64,
        "private_key_b64": priv_b64,
    }, indent=2))


def cmd_set_tier(args: argparse.Namespace) -> None:
    reg = load_reg(Path(args.registry))
    prev = reg["peers"].get(args.node_id, {})
    reg["peers"][args.node_id] = {
        "label": args.label or prev.get("label") or args.node_id,
        "public_key_b64": args.public_key_b64,
        "tier": args.tier,
        "strikes": prev.get("strikes", 0),
    }
    save_reg(Path(args.registry), reg)
    print(f"SET {args.node_id} tier={args.tier} file={args.registry}")


def cmd_strike(args: argparse.Namespace) -> None:
    reg = load_reg(Path(args.registry))
    peer = reg["peers"].get(args.node_id)
    if not peer:
        raise SystemExit(f"Unknown node_id: {args.node_id}")
    peer["strikes"] = int(peer.get("strikes", 0)) + 1
    if peer["strikes"] >= args.max_strikes:
        peer["tier"] = "quarantined"
    save_reg(Path(args.registry), reg)
    print(f"STRIKE {args.node_id} strikes={peer['strikes']} tier={peer['tier']}")


def cmd_sign(args: argparse.Namespace) -> None:
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(args.private_key_b64))
    msg = args.message.encode("utf-8")
    sig_b64 = base64.b64encode(priv.sign(msg)).decode("ascii")
    print(sig_b64)


def cmd_verify(args: argparse.Namespace) -> None:
    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(args.public_key_b64))
    pub.verify(base64.b64decode(args.signature_b64), args.message.encode("utf-8"))
    print("VERIFIED_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=str(DEFAULT_REG))
    sub = ap.add_subparsers(dest="cmd", required=True)

    k = sub.add_parser("keygen")
    k.add_argument("--label", required=True)
    k.set_defaults(func=cmd_keygen)

    t = sub.add_parser("set-tier")
    t.add_argument("--node-id", required=True)
    t.add_argument("--public-key-b64", required=True)
    t.add_argument("--tier", required=True, choices=["operator", "external", "quarantined"])
    t.add_argument("--label", default="")
    t.set_defaults(func=cmd_set_tier)

    s = sub.add_parser("strike")
    s.add_argument("--node-id", required=True)
    s.add_argument("--max-strikes", type=int, default=3)
    s.set_defaults(func=cmd_strike)

    sg = sub.add_parser("sign")
    sg.add_argument("--private-key-b64", required=True)
    sg.add_argument("--message", required=True)
    sg.set_defaults(func=cmd_sign)

    vr = sub.add_parser("verify")
    vr.add_argument("--public-key-b64", required=True)
    vr.add_argument("--signature-b64", required=True)
    vr.add_argument("--message", required=True)
    vr.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
