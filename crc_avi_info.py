from typing import Optional
import numpy as np
from textwrap import wrap

def hex2bin(hexstr: str) -> str:
    """Convert a hexadecimal string to binary string, with zero fillings."""
    num_of_bits = len(hexstr) * 4
    binstr = bin(int(hexstr, 16))[2:].zfill(int(num_of_bits))
    return binstr


def hex2int(hexstr: str) -> int:
    """Convert a hexadecimal string to integer."""
    return int(hexstr, 16)


def bin2int(binstr: str) -> int:
    """Convert a binary string to integer."""
    return int(binstr, 2)


def bin2hex(binstr: str) -> str:
    """Convert a binary string to hexadecimal string."""
    return "{0:X}".format(int(binstr, 2))


def df(msg: str) -> int:
    """Decode Downlink Format value, bits 1 to 5."""
    dfbin = hex2bin(msg[:2])
    return min(bin2int(dfbin[0:5]), 24)

def crc(msg: str, encode: bool = False) -> int:
    """Mode-S Cyclic Redundancy Check.

    Detect if bit error occurs in the Mode-S message. When encode option is on,
    the checksum is generated.

    Args:
        msg: 28 bytes hexadecimal message string
        encode: True to encode the date only and return the checksum
    Returns:
        int: message checksum, or partity bits (encoder)

    """
    # the CRC generator
    G = [int("11111111", 2), int("11111010", 2), int("00000100", 2), int("10000000", 2)]

    if encode:
        msg = msg[:-6] + "000000"

    msgbin = hex2bin(msg)
    msgbin_split = wrap(msgbin, 8)
    mbytes = list(map(bin2int, msgbin_split))

    for ibyte in range(len(mbytes) - 3):
        for ibit in range(8):
            mask = 0x80 >> ibit
            bits = mbytes[ibyte] & mask

            if bits > 0:
                mbytes[ibyte] = mbytes[ibyte] ^ (G[0] >> ibit)
                mbytes[ibyte + 1] = mbytes[ibyte + 1] ^ (
                    0xFF & ((G[0] << 8 - ibit) | (G[1] >> ibit))
                )
                mbytes[ibyte + 2] = mbytes[ibyte + 2] ^ (
                    0xFF & ((G[1] << 8 - ibit) | (G[2] >> ibit))
                )
                mbytes[ibyte + 3] = mbytes[ibyte + 3] ^ (
                    0xFF & ((G[2] << 8 - ibit) | (G[3] >> ibit))
                )

    result = (mbytes[-3] << 16) | (mbytes[-2] << 8) | mbytes[-1]

    return result


def crc_legacy(msg: str, encode: bool = False) -> int:
    """Mode-S Cyclic Redundancy Check. (Legacy code, 2x slow)."""
    # the polynominal generattor code for CRC [1111111111111010000001001]
    generator = np.array(
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1]
    )
    ng = len(generator)

    msgnpbin = np.array([int(i) for i in hex2bin(msg)])

    if encode:
        msgnpbin[-24:] = [0] * 24

    # loop all bits, except last 24 piraty bits
    for i in range(len(msgnpbin) - 24):
        if msgnpbin[i] == 0:
            continue

        # perform XOR, when 1
        msgnpbin[i : i + ng] = np.bitwise_xor(msgnpbin[i : i + ng], generator)

    # last 24 bits
    msgbin = np.array2string(msgnpbin[-24:], separator="")[1:-1]
    reminder = bin2int(msgbin)

    return reminder

f1 = open("FoundMsg.txt", "r+")

binmsg = f1.readline()
msg = pms.bin2hex(binmsg)
print( crc(msg))
if crc(msg) == 0 :
	print("msg is correct and :")
	print("type code is", pms.typecode(msg))
	pms.tell(msg)
else :
	print("incorrect msg")
