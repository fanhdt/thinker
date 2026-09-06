from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def get_current_date_time(timezone: str = "Asia/Jakarta") -> str:
    """Dapatkan tanggal dan waktu saat ini.

    Args:
        timezone : Nama timezone IANA, contoh "Asia/Jakarta", "UTC",
            "Amerika/New_York". Default "Asia/Jakarta" (WIB)
    """

    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return (
            f"Error : timezone '{timezone}' tidak dikenali. "
            "gunakan format IANA, mis. 'Asia/Jakarta'"
        )

    now = datetime.now(tz)
    return now.strftime("%A, %d %B %Y, pukul %H:M:S(%Z)")
