import pyModeS as pms

f1 = open("FoundMsg.txt", "r+")
binmsg = f1.readline()
msg = pms.bin2hex(binmsg)
pms.crc(msg)
pms.typecode(msg)
pms.tell(msg)

print(pms.typecode(msg))