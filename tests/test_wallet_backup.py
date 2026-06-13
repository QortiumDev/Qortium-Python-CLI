import hashlib
import hmac
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from qortium_cli.crypto import b58decode, b58encode, qortal_hub_kdf
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.tools import export_wallet_backup
from qortium_cli.wallet_backup import (
    MASTER_SEED_BYTES,
    QORTIUM_PRIVATE_KEY_WALLET_VERSION,
    QORTIUM_WALLET_VERSION,
    decode_private_key_input,
    derive_address_seed,
    default_wallet_backup_path,
    generate_new_wallet_backup,
    generate_wallet_backup_from_master_seed,
    generate_wallet_backup_from_private_key,
    normalize_wallet_file_path,
    private_key_from_wallet,
    qortal_address_from_private_seed,
    write_wallet_backup,
)


def make_context(private_key: str, address: str) -> AppContext:
    return AppContext(
        settings_dir=Path("."),
        endpoint=EndpointSettings(base_url="http://127.0.0.1:24891", timeout_seconds=15),
        account=AccountSettings(
            name="tester",
            account_address=address,
            public_key="public-key",
            private_key=private_key,
            api_key="api-key",
        ),
        chat=ChatSettings(),
        debug=False,
    )


def encrypted_wallet_payload(payload: bytes, address: str, password: str, version: int) -> dict:
    key = qortal_hub_kdf(password)
    iv = bytes(range(16))
    salt = bytes(range(32, 64))
    encryptor = Cipher(
        algorithms.AES(key[:32]),
        modes.CBC(iv),
    ).encryptor()
    encrypted_seed = encryptor.update(payload) + encryptor.finalize()
    mac = hmac.new(key[32:63], encrypted_seed, hashlib.sha512).digest()
    return {
        "address0": address,
        "encryptedSeed": b58encode(encrypted_seed),
        "salt": b58encode(salt),
        "iv": b58encode(iv),
        "version": version,
        "mac": b58encode(mac),
        "kdfThreads": 16,
    }


class WalletBackupTests(TestCase):
    def test_qortium_home_crypto_matches_javascript_vector(self) -> None:
        payload = bytes(range(32))
        iv = bytes(range(16))
        key = qortal_hub_kdf("qortium-test-password")
        encryptor = Cipher(
            algorithms.AES(key[:32]),
            modes.CBC(iv),
        ).encryptor()
        encrypted_seed = encryptor.update(payload) + encryptor.finalize()
        mac = hmac.new(key[32:63], encrypted_seed, hashlib.sha512).digest()

        self.assertEqual(
            key.hex(),
            "6ede17d8e313db973d06d05d1460a1e31e1ec99d04f608e3796c8ca7b2f4f17"
            "2f9037b8ebda45b3b4ab391fea354687d317dbec91a9597b3f5c5979cb310176d",
        )
        self.assertEqual(
            encrypted_seed.hex(),
            "e620b0d027ba85168652eff7072c04c930c43567376fb62cdd5c918f8f046282",
        )
        self.assertEqual(
            mac.hex(),
            "de81ba8a7153235a327c36d2848a4b49000d0815ce6fbf877a9094e575ac7983"
            "35b3532f583ffdbbddb8e03c424c7c0f5249484fa1ecac108b2d728a7237e42e",
        )

    def test_qortium_home_backup_decrypts_to_original_private_seed(self) -> None:
        seed = bytes(range(32))
        private_key = b58encode(seed)
        address = qortal_address_from_private_seed(seed)
        key = bytes(range(64))
        salt = bytes(range(32, 64))
        iv = bytes(range(16))

        with patch("qortium_cli.wallet_backup.qortal_hub_kdf", return_value=key):
            backup = generate_wallet_backup_from_private_key(
                private_key,
                address,
                "backup-password",
                salt=salt,
                iv=iv,
            )

        encrypted_seed = b58decode(backup["encryptedSeed"])
        decryptor = Cipher(
            algorithms.AES(key[:32]),
            modes.CBC(iv),
        ).decryptor()
        decrypted_seed = decryptor.update(encrypted_seed) + decryptor.finalize()
        expected_mac = hmac.new(key[32:63], encrypted_seed, hashlib.sha512).digest()

        self.assertEqual(decrypted_seed, seed)
        self.assertEqual(b58decode(backup["mac"]), expected_mac)
        self.assertEqual(backup["address0"], address)
        self.assertEqual(
            backup["version"],
            QORTIUM_PRIVATE_KEY_WALLET_VERSION,
        )
        self.assertEqual(backup["kdfThreads"], 16)

    def test_master_seed_wallet_backup_decrypts_to_address_zero_key(self) -> None:
        master_seed = bytes(range(MASTER_SEED_BYTES))
        private_seed = derive_address_seed(master_seed, 0)
        address = qortal_address_from_private_seed(private_seed)
        key = bytes(range(64))
        salt = bytes(range(32, 64))
        iv = bytes(range(16))

        with patch("qortium_cli.wallet_backup.qortal_hub_kdf", return_value=key):
            generated = generate_wallet_backup_from_master_seed(
                master_seed,
                "backup-password",
                salt=salt,
                iv=iv,
            )
            restored_private_key = private_key_from_wallet(
                generated.wallet,
                "backup-password",
            )

        encrypted_seed = b58decode(generated.wallet["encryptedSeed"])
        decryptor = Cipher(
            algorithms.AES(key[:32]),
            modes.CBC(iv),
        ).decryptor()
        decrypted_seed = decryptor.update(encrypted_seed) + decryptor.finalize()

        self.assertEqual(generated.address, address)
        self.assertEqual(generated.private_key, b58encode(private_seed))
        self.assertEqual(restored_private_key, generated.private_key)
        self.assertEqual(decrypted_seed, master_seed)
        self.assertEqual(generated.wallet["address0"], address)
        self.assertEqual(generated.wallet["version"], QORTIUM_WALLET_VERSION)

    def test_generate_new_wallet_backup_uses_random_master_seed(self) -> None:
        master_seed = bytes(range(MASTER_SEED_BYTES))

        with patch(
            "qortium_cli.wallet_backup.os.urandom",
            side_effect=[master_seed, bytes(32), bytes(16)],
        ) as urandom:
            generated = generate_new_wallet_backup("backup-password")

        self.assertEqual(urandom.call_args_list[0].args, (MASTER_SEED_BYTES,))
        self.assertEqual(
            generated.private_key,
            b58encode(derive_address_seed(master_seed, 0)),
        )
        self.assertEqual(generated.wallet["version"], QORTIUM_WALLET_VERSION)

    def test_master_seed_wallet_backup_rejects_wrong_seed_length(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly 64 bytes"):
            generate_wallet_backup_from_master_seed(b"short", "backup-password")

    def test_qortium_home_64_byte_secret_key_uses_first_32_bytes(self) -> None:
        seed = bytes(range(32))
        secret_key = seed + bytes(reversed(range(32)))

        self.assertEqual(decode_private_key_input(b58encode(secret_key)), seed)

    def test_normalize_wallet_file_path_accepts_dragged_terminal_paths(self) -> None:
        quoted_path = "'/home/user/Downloads/qortium-docs/wallet.json' "
        escaped_path = "/home/user/Downloads/qortium-docs/My\\ Wallet.json"

        self.assertEqual(
            normalize_wallet_file_path(quoted_path),
            Path("/home/user/Downloads/qortium-docs/wallet.json"),
        )
        self.assertEqual(
            normalize_wallet_file_path(escaped_path),
            Path("/home/user/Downloads/qortium-docs/My Wallet.json"),
        )

    def test_private_key_from_version_3_wallet_file_payload(self) -> None:
        seed = bytes(range(32))
        address = qortal_address_from_private_seed(seed)
        wallet = encrypted_wallet_payload(
            seed,
            address,
            "wallet-password",
            QORTIUM_PRIVATE_KEY_WALLET_VERSION,
        )

        self.assertEqual(private_key_from_wallet(wallet, "wallet-password"), b58encode(seed))

    def test_private_key_from_version_2_wallet_file_payload(self) -> None:
        master_seed = bytes(range(64))
        private_seed = derive_address_seed(master_seed, 0)
        address = qortal_address_from_private_seed(private_seed)
        wallet = encrypted_wallet_payload(
            master_seed,
            address,
            "wallet-password",
            QORTIUM_WALLET_VERSION,
        )

        self.assertEqual(
            private_key_from_wallet(wallet, "wallet-password"),
            b58encode(private_seed),
        )

    def test_private_key_from_wallet_rejects_wrong_password(self) -> None:
        seed = bytes(range(32))
        address = qortal_address_from_private_seed(seed)
        wallet = encrypted_wallet_payload(
            seed,
            address,
            "wallet-password",
            QORTIUM_PRIVATE_KEY_WALLET_VERSION,
        )

        with self.assertRaisesRegex(ValueError, "Incorrect wallet password"):
            private_key_from_wallet(wallet, "wrong-password")

    def test_backup_rejects_private_key_for_another_address(self) -> None:
        private_key = b58encode(bytes(range(32)))
        other_address = qortal_address_from_private_seed(bytes(range(1, 33)))

        with self.assertRaisesRegex(
            ValueError,
            "does not match the configured wallet address",
        ):
            generate_wallet_backup_from_private_key(
                private_key,
                other_address,
                "backup-password",
            )

    def test_write_wallet_backup_writes_json(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "qortium_backup_test.json"
            backup = {"address0": "Qtest", "version": 1}

            saved_path = write_wallet_backup(path, backup)

            self.assertEqual(saved_path, path.resolve())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), backup)
            self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))

    def test_default_backup_name_matches_qortium_home(self) -> None:
        address = "Qtest"

        self.assertEqual(
            default_wallet_backup_path(address, wallet_name="My Wallet").name,
            "My Wallet_Qtest.json",
        )

    def test_export_password_mismatch_does_not_write(self) -> None:
        seed = bytes(range(32))
        ctx = make_context(b58encode(seed), qortal_address_from_private_seed(seed))

        with (
            patch(
                "qortium_cli.tools.prompt_secret",
                side_effect=[
                    "first-password",
                    "different-password",
                ],
            ),
            patch("qortium_cli.tools.prompt_str", return_value="tester"),
            patch(
                "qortium_cli.tools.generate_wallet_backup_from_private_key"
            ) as generate_backup,
            patch("qortium_cli.tools.write_wallet_backup") as write_backup,
        ):
            export_wallet_backup(ctx)

        generate_backup.assert_not_called()
        write_backup.assert_not_called()

    def test_export_backup_uses_configured_private_key(self) -> None:
        seed = bytes(range(32))
        private_key = b58encode(seed)
        address = qortal_address_from_private_seed(seed)
        ctx = make_context(private_key, address)
        output_path = Path("qortium_backup_test.json")
        backup = {
            "address0": address,
            "version": QORTIUM_PRIVATE_KEY_WALLET_VERSION,
        }

        with (
            patch(
                "qortium_cli.tools.prompt_secret",
                side_effect=[
                    "backup-password",
                    "backup-password",
                ],
            ),
            patch(
                "qortium_cli.tools.prompt_str",
                side_effect=["My Wallet", str(output_path)],
            ),
            patch(
                "qortium_cli.tools.default_wallet_backup_path",
                return_value=output_path,
            ) as default_path,
            patch(
                "qortium_cli.tools.generate_wallet_backup_from_private_key",
                return_value=backup,
            ) as generate_backup,
            patch(
                "qortium_cli.tools.write_wallet_backup",
                return_value=output_path,
            ) as write_backup,
        ):
            export_wallet_backup(ctx)

        default_path.assert_called_once_with(address, wallet_name="My Wallet")
        generate_backup.assert_called_once_with(
            private_key,
            address,
            "backup-password",
        )
        write_backup.assert_called_once_with(output_path, backup)
