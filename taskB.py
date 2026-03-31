import pyModeS as pms

#this section of the code converts an array of bits into hex and finds the type code and prints the results (bin,hex,type code)
#along with other info that the func tell provides

arr=[1, 0, 0, 0, 1, 1, 0, 1, 0, 1, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 1, 0, 1, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 1, 1, 0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 0]
bin_in = ''.join(str(digit) for digit in arr)
hex_out = pms.bin2hex(bin_in)
type = pms.typecode(hex_out)
print(f"binary: {bin_in}")
print(f"Hex: {hex_out}")
pms.tell(hex_out)
print(f"type code = {type}")

#this section calculates the the position using the position func (lat,lon)

msg0 = "8D40621D58C382D690C8AC2863A7"
msg1 = "8D40621D58C386435CC412692AD6"
t0 = 1457996402
t1 = 1457996400
A = pms.adsb.position(msg0, msg1, t0, t1)
print(A)