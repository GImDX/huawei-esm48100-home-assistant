"""Pure helpers shared by the integration and its tests."""


def parse_slave_addresses(value: str | list[int]) -> list[int]:
    """Parse and validate a list of Modbus slave addresses."""
    if isinstance(value, list):
        addresses = value
    else:
        try:
            addresses = [
                int(part.strip(), 0) for part in value.split(",") if part.strip()
            ]
        except ValueError as err:
            raise ValueError(
                "slave addresses must be decimal or 0x-prefixed integers"
            ) from err

    if not addresses:
        raise ValueError("at least one slave address is required")
    if any(not 1 <= address <= 247 for address in addresses):
        raise ValueError("slave addresses must be between 1 and 247")
    if len(set(addresses)) != len(addresses):
        raise ValueError("slave addresses must not contain duplicates")
    return addresses


def format_slave_addresses(addresses: list[int]) -> str:
    """Format addresses for display in the config flow."""
    return ", ".join(f"0x{address:02X}" for address in addresses)
