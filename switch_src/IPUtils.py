import math, logging, traceback
from ipaddress import ip_address, ip_network
log = logging.getLogger(__name__)

def ip_inc(ipstring, octet=3, inc=1):
	ip = ipstring.split('.')
	ip[octet] = (int(ip[octet]) + inc)
	if ip[octet] > 255:
		ip[octet] %= 256
		return ip_inc('.'.join(str(x) for x in ip), octet - 1)
	return '.'.join(str(x) for x in ip)

'''
	Returns -1 if ipA is a lower IP address than ipB
	Returns 1 if ipA is a lower IP address than ipB
	Returns 0 if IPs are the same
'''
def ip_compare(ipA, ipB):
	aOctets = ipA.strip().split('.')
	bOctets = ipB.strip().split('.')
	for i in range(len(aOctets)):
		a = int(aOctets[i])
		b = int(bOctets[i])
		if a < b:
			return -1
		if a > b:
			return 1
	return 0

def ip_to_decimal(ip):
	log.debug(f'%s: Converting ip {ip} to decimal value')
	if ip == 'F':
		return 0
	octets = ip.split('.')
	decimal = 0
	for i in range(len(octets)):
		decimal += int(octets[i]) * pow(2, 8*(3-i))
	return decimal

def decimal_to_bits(octet, base):
	if octet % 2**base == 0:
		return 8 - base
	return decimal_to_bits(octet, base - 1)
	
def mask_to_cidr(mask):
	octets = mask.split('.')
	bits = 0
	for octet in octets:
		if int(octet) == 255:
			bits += 8
		else:
			bits += decimal_to_bits(int(octet), 7)
	return str(bits)

def wildcard_to_cidr(mask):
	octets = mask.split('.')
	bits = 0
	for octet in octets:
		if int(octet) == 0:
			bits += 8
		else:
			bits += decimal_to_bits(255-int(octet), 7)
	return str(bits)

def cidr_to_mask(cidr):
	int_cidr = int(cidr)
	print('int_cidr: %d' % int_cidr)
	mask = []
	subnet_bits = math.floor(int_cidr / 8)
	print('subnet_bits: %d' % subnet_bits)
	host_bits = 256 - pow(2,(8-(int_cidr % 8)))
	print('host_bits: %d' % host_bits)
	for i in range(4):
		if i < subnet_bits:
			mask.append('255')
		elif i == subnet_bits:
			mask.append(str(host_bits))
		else:
			mask.append('0')
	return '.'.join(mask)

def range_to_cidr(range):
	ips = range.split('-')
	if len(ips) > 2:
		raise Exception('Bad range in CIDR conversion.')
	startOctets = ips[0].split('.')
	endOctets = ips[1].split('.')
	
	if len(startOctets) != len(endOctets):
		raise Exception('Bad IP in CIDR conversion.')
	
	ipCount = 0
	for i in range(len(startOctets)):
		ipCount+= pow(256,i) * (endOctets[-i] - startOctets[-i])
	cidr = 32 - round(math.log(ipCount,2))
	return cidr

'''
	Converts a CIDR formatted network string into an IP address range start and end
	@param(cidr_format) 	
		must be a properly formatted CIDR address: '192.168.0.0/24'
	returns
		network: starting IP for supplied range: '192.168.0.0'
		subnet_stop: ending IP for supplied range: '192.168.0.255'
'''
def cidr_to_range(cidr_format):
	if not '/' in cidr_format:
		raise ValueError(f'{cidr_format} is not a valid CIDR formatted address')
	network,cidr = cidr_format.split('/')
	subnet_size = pow(2, 32-int(cidr)) - 1
	octets = network.split('.')
	last_ip = int(octets[3]) + subnet_size
	octets[3] = str(last_ip)
	subnet_stop = '.'.join(octets)
	return network, subnet_stop

'''
	Generates a list of all IPs in a range proided as either a range or a start,end
	@param(ips) must be a list: 
		range denoted with a '-': '192.168.0.0-192.168.0.255'
		range in CIDR format: '192.168.0.0/24'
		single IP address: '192.168.0.1'
	returns
		iplist - a list of IP addreses including @param(ip_start) and @param(ip_end)
	i.e.
	['192.168.0.0','192.168.0.1','192.168.0.2','...','192.168.0.255']
'''
def geniplist(subnets):
	iplist = []
	for subnet in subnets:
		try:
			# Handle CIDR format
			if '/' in subnet:
				start,end = cidr_to_range(subnet)
				while ip_compare(start,end) <= 0:
					iplist.append(start)
					start = ip_inc(start)
			# Handle range in '-' format
			elif '-' in subnet:
				start,end = subnet.split('-')
				while ip_compare(start,end) <= 0:
					iplist.append(start)
					start = ip_inc(start)
			# Handle individual IP
			else:
				iplist.append(subnet)
		except:
			log.error(f'%s: Bad range supplied {subnet}', 'geniplist')
			log.error(f'%s: {traceback.print_exc()}','geniplist')
	return iplist

def ip_to_subnet(ip, mask):
	mask_bits = mask.split('.')
	ip_bits = ip.split('.')
	subnet = []

	hostbit = False
	for i in range(4):
		if hostbit:
			subnet.append('0')
		if mask_bits[i] != '255':
			subnet_size = 256 - int(mask_bits[i])
			host = int(ip_bits[i])
			subnet_begin = host - (host % subnet_size)
			subnet.append(str(subnet_begin))
			hostbit = True
		else:
			subnet.append(ip_bits[i])
	return '.'.join(subnet) + '/' + mask_to_cidr('.'.join(mask_bits))

def ip_in_subnet(ip, network, wildcard_mask='0.0.0.0'):
	if network == 'host':
		network = wildcard_mask
		wildcard_mask = '0.0.0.0'
	if wildcard_mask == '0.0.0.0':
		return ip == network
	if network == 'any' or ip == wildcard_mask:
		return True
	try: 
		cidr = wildcard_to_cidr(wildcard_mask)
		subnet = ip_network(f'{network}/{cidr}')
		return ip_address(ip) in subnet
	except:
		log.error(f'%s: Error processing IP: {ip} Network: {network} {wildcard_mask}','ip_in_subnet')
		log.error(f'%s: {traceback.print_exc()}', 'ip_in_subnet')
	return False