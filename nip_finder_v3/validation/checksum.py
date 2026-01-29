"""
Walidacja checksum NIP.
"""

import logging

logger = logging.getLogger(__name__)


class ChecksumValidator:
    """
    Walidator checksum NIP.

    Algorytm:
    1. Wagi: [6, 5, 7, 2, 3, 4, 5, 6, 7]
    2. Suma = sum(cyfra[i] * waga[i] for i in 0..8)
    3. Checksum = Suma % 11
    4. Checksum nie może być 10
    5. Checksum musi być równy 10-tej cyfrze
    """

    def validate(self, nip: str) -> bool:
        """
        Waliduje checksum NIP.

        Args:
            nip: NIP (10 cyfr)

        Returns:
            True jeśli checksum poprawny
        """
        if not nip or len(nip) != 10 or not nip.isdigit():
            logger.debug("Checksum: nieprawidłowy format NIP: %s", nip)
            return False

        # Wagi dla checksum
        weights = [6, 5, 7, 2, 3, 4, 5, 6, 7]

        # Suma ważona
        checksum = sum(int(nip[i]) * weights[i] for i in range(9)) % 11

        # Checksum nie może być 10 (NIP nieprawidłowy)
        if checksum == 10:
            logger.debug("Checksum: checksum == 10 (nieprawidłowy NIP)")
            return False

        # Checksum musi być równy 10-tej cyfrze
        valid = checksum == int(nip[9])

        if valid:
            logger.debug("✅ Checksum: NIP %s jest poprawny", nip)
        else:
            logger.debug("❌ Checksum: NIP %s jest niepoprawny (oczekiwano %d, otrzymano %s)",
                        nip, checksum, nip[9])

        return valid
