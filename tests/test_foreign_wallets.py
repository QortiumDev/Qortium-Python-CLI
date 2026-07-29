from __future__ import annotations

from unittest import TestCase

from qortium_cli.crypto import b58encode
from qortium_cli.foreign_wallets import derive_foreign_wallet


class ForeignWalletDerivationTests(TestCase):
    """Vectors generated directly from Qortium Home's foreign-wallets.ts."""

    PRIVATE_KEY = b58encode(bytes(range(32)))
    VECTORS = {
        "BTC": (
            "1A9G3q16XmzmVDF72DvSZEK37ZzZUrNmK1",
            "xpub661MyMwAqRbcFtt61PnRrkS3rTbfuoSzFdQToo7EWMYiDNoqdiBPczzQAUhxLRyRbdiVjLoT1noDubccztGBrGEzvj63fsS58UeGxfuyivb",
        ),
        "LTC": (
            "LYn1W4kqTV1KYcdBomcQ5HdKr9GprWhTY2",
            "xpub661MyMwAqRbcEeGMkZu4CuQ2DQAs9N9tUSmyWSqZRvshiE5FQwcVzdaVj8dNkt618jxT2UGzvYs4eieqNU8GWQY6jPMuHR2SdSZicSgnJVZ",
        ),
        "DOGE": (
            "DFxiKGpTHGfyeyo67P7nzXJ57DxRArZy9q",
            "dgub8kXBZ7ymNWy2TBrQUZ5vm9RVY3p1CK96HkfWU7BXLAXTEmUPSb1o7doAGnokfd8jhUAHK8qhRSbyiMWNTbGJzWdpTKeCSL7RorFvxk7ywk4",
        ),
        "DGB": (
            "DSdpkc557DEnhYm3QM66tK8DmrmjtVon6V",
            "xpub661MyMwAqRbcG37CaNum4X7eZLavWF1NQ2wsz2tTSK78Ed4uCyZAFM85GHKNMogEQf4rYSM4NcaE65WkeXUjsFU6cKbxCfzBbiEAeJV2dqA",
        ),
        "RVN": (
            "RLDxaPHNqrBXDR1utACFqLzDq1jwUj7wug",
            "xpub661MyMwAqRbcFcm4bHdVHhga8qn9mXuzYFvy6CnwR3C2LC3UgPNt1XP7yxv8wt3aRpnpUe3pLgAC3jFstrG41B6KTKEiV3Z3NEM7JozWRJf",
        ),
        "DASH": (
            "Xmu1XiX7SGQQKPrJeCGBTPpxxhDvtgtqzx",
            "xpub661MyMwAqRbcFRRD86iFYGziai4CYKBteibXo43ZViXo6KT5Qsxr4y4vAgHifuAcA9PCJEggH1QCG9N2KqQoGHqMZeiuzmBvdGAvFUvm44T",
        ),
        "NMC": (
            "NBECC4BWAJcPhg62asPDqh7BZbiutDKFYb",
            "xpub661MyMwAqRbcEmbvFixXUhVxcRyY1xvhdSAhzs87m59TqTPcheTSVEM43hsPZUuHFmxWkQxuJMrXbz2QB5mPGnWvHRtaeFtUvb9AuNdBYxC",
        ),
        "FIRO": (
            "aMKc3acrAjVADbeGiktpadJcTmdqm1jXmr",
            "xpub661MyMwAqRbcGkenRzvzXxYxg5Qx2MR3tGmQy1EfPLU6LudjeWASoHy7CnNNek14HMNFkxWNYKSVUs3jWBnJFkXpx8KgtQWPYXNNhb7UWDj",
        ),
    }

    def test_matches_qortium_home_vectors(self) -> None:
        for coin, (expected_address, expected_xpub) in self.VECTORS.items():
            with self.subTest(coin=coin):
                wallet = derive_foreign_wallet(self.PRIVATE_KEY, coin)
                self.assertEqual(wallet.address, expected_address)
                self.assertEqual(wallet.xpub58, expected_xpub)

    def test_ed25519_secret_key_uses_its_first_32_byte_seed(self) -> None:
        seed = bytes(range(32))
        secret_key = b58encode(seed + bytes(reversed(seed)))
        self.assertEqual(
            derive_foreign_wallet(secret_key, "BTC"),
            derive_foreign_wallet(b58encode(seed), "BTC"),
        )

    def test_unknown_wallet_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported Qortium"):
            derive_foreign_wallet(self.PRIVATE_KEY, "unknown")
