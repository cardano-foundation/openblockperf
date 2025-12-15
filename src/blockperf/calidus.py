import binascii
import json
from pathlib import Path

import cbor2
from nacl.encoding import HexEncoder, RawEncoder
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey
from pycardano import PaymentExtendedSigningKey, PaymentVerificationKey


def parse_key_file(file_path: Path) -> dict:
    """
    Parse a key file
    """
    if not file_path.exists():
        raise Exception(f"Path not found: {file_path}")

    with open(file_path) as f:
        return json.load(f)


def extract_signing_key_from_cbor(cbor_hex: str) -> PaymentExtendedSigningKey:
    """
    Extract raw Ed25519 signing key from cborHex format.

    For extended signing keys (128 bytes total):
    - CBOR prefix: 5880 (byte string of 128 bytes)
    - First 64 bytes: Extended private key (32 bytes key + 32 bytes extension)
    - Last 64 bytes: Chain code + other metadata

    For signing, we need the first 32 bytes of the private key portion.

    Args:
        cbor_hex: Hex-encoded CBOR data from .skey file

    Returns:
        32-byte Ed25519 signing key
    """
    raw_signing_bytes = cbor2.loads(binascii.unhexlify(cbor_hex))
    return PaymentExtendedSigningKey.from_primitive(raw_signing_bytes)
