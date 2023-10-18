# $language = "Python"
# $interface = "1.0"


#
#	Author: A1C Gonnella, Bryan
#	1 APR 2021


import os, json, traceback, logging
from ipaddress import ip_address, ip_network
from datetime import datetime

log = logging.Logger(__name__)

# Compare serial lists of two stacks: 
# returns Added, Removed lists
def stack_compare(old, current):
	added = current.copy()
	removed = old.copy()
	for serial in old:
		if serial in current:
			removed.remove(serial)
			added.remove(serial)
	return added, removed

'''
	Takes @param(grouplist) - a dictionary of subnets keyed by group name 
	and merges them into the existing dictionary and write to @param(outfile)

	Returns the merged dictionaries:
	Both @param(grouplist) and @return(mergelist) are formatted as ex.:
	{
		'GROUP1': {
			'192.168.1.1' : {...},
			'192.168.1.2' : {...},
			...,
			'192.168.1.255' : {...},
		},
		'GROUP2': {
			'192.168.2.1' : {...},
			'192.168.2.2' : {...},
			...,
			'192.168.2.255' : {...},
		}
	}
'''
def savelist(grouplist, mergelist, outfile):
	info_keys = ['Last Updated','Make','Hostname','IP Address','Subnet Mask','Firmware','Serial','FIPS Mode','Upstream','Last Seen Online']
	today = datetime.now().strftime("%d%b%Y")
	if not os.path.exists(outfile):
		log.warning(f'%s: Creating store file: {os.path.abspath(outfile)}', 'savelist')
	with open(outfile, 'w+') as listfile:
		for subnet_group in grouplist:
			mergelist.setdefault(subnet_group,{})
			for group_name in grouplist[subnet_group]:
				mergelist[subnet_group].setdefault(group_name,{})
				for ip in grouplist[subnet_group][group_name]:
					status = grouplist[subnet_group][group_name][ip]['Make']
					mergelist[subnet_group][group_name].setdefault(ip, {})
					mergelist[subnet_group][group_name][ip]['Make'] = status
					mergelist[subnet_group][group_name][ip]['Last Updated'] = today
					if status == 'Reserved':
						mergelist[subnet_group][group_name][ip] = grouplist[subnet_group][group_name][ip]
						continue
					if status == 'Offline':
						for key in info_keys:
							if not key in mergelist[subnet_group][group_name][ip].keys():
								if key == 'IP Address':
									mergelist[subnet_group][group_name][ip][key] = ip
								else:
									mergelist[subnet_group][group_name][ip][key] = ''
						continue
					mergelist[subnet_group][group_name][ip]['Last Seen Online'] = today
					if status == 'NOLOGIN':
						continue
					mergelist[subnet_group][group_name][ip].update(grouplist[subnet_group][group_name][ip])
		json.dump(mergelist, listfile, indent=4)
	return mergelist

'''
	Pulls all information from and returns JSON representation of device @param(switch)
'''
def map_host(switch):
	if not switch:
		raise Exception('Offline')
	try:
		if switch.make == 'Cisco':
			switch.readinfo()
			switch.parse_domain()
			switch.parse_interfaces()
			switch.parse_upstream()
			switch.parse_cdp()
			switch.parse_fips()
		else:
			switch.readinfo()
	except:
		log.error(f'%s: {traceback.print_exc()}','map_host')
	finally:
		if switch and switch.connected:
			switch.disconnect()
	return switch.json()

'''
	Returns a list of IP addresses in a range denoted with a '-'
	ex: 
	@param(ip_range) = '192.168.1.10-192.168.1.20'
	returns:
		['192.168.1.10','192.168.1.11',..'192.168.1.20']
'''
def get_ip_range(range_string):
	if not '-' in range_string:
		return range_string
	ip_range = []
	start, stop = range_string.split('-')
	ip_start = ip_address(start)
	ip_stop = ip_address(stop)
	while ip_start < ip_stop:
		ip_range.append(str(ip_start))
		ip_start+= 1
	ip_range.append(str(ip_stop))
	return ip_range


'''
	Returns a dictionary of groups mapped to a list of their respective IP addresses as well as
	a dictionary of reserved IP addresses mapped to exhaustive device information - these should not be scanned
	ex.
	{
		'GROUP1': {
			'SUBNET1': ['192.168.1.0','192.168.1.2','192.168.1.2',...,'192.168.1.255'],
			'SUBNET1': ['192.168.2.0','192.168.2.2','192.168.2.2',...,'192.168.2.255']
		}
	},
	# Note the reserved map is a separate returned value
	{
		'192.168.1.1': {
			'Hostname': 'EXAMPLE_SWITCH',
            'IP Address': '192.168.1.1',
            'Subnet Mask': '255.255.255.0',
            'Make': 'Cisco',
            'Model': 'C9300-48U',
            'Firmware': 'IOS-XE 16.12.1',
            'Serial': 'FOT1234567X',
            'Upstream': 'EXAMPLE-DN Gi1/1/1',
            'FIPS Mode': 'YES (ON REBOOT)'
		}
	}
'''
def parse_list(ip_dict):	
	subnets = {}
	reserved = {}
	for group in ip_dict:
		for group_name in ip_dict[group]:
			group_subnets = []
			subnets.setdefault(group, {})
			for subnet in ip_dict[group][group_name]:
				log.debug(f'%s: Parsing subnet {subnet}', 'load_list')
				if '-' in subnet:
					group_subnets+= get_ip_range(subnet)
					continue
				iplist = ip_network(subnet)
				if '/' in subnet:
					network_addr = str(iplist.network_address)
					reserved[network_addr] = {
						'Hostname': group_name,
						'IP Address': network_addr,
						'Subnet Mask': 'NETWORK',
						'Make': 'Reserved',
						'Model': [],
						'Firmware': '',
						'Serial': [],
						'FIPS Mode': ''
					}
					broadcast_addr = str(iplist.broadcast_address)
					reserved[broadcast_addr] = {
						'Hostname': 'BROADCAST',
						'IP Address': broadcast_addr,
						'Subnet Mask': 'BROADCAST',
						'Make': 'Reserved',
						'Model': [],
						'Firmware': '',
						'Serial': [],
						'FIPS Mode': ''
					}
				group_subnets+= [str(ip) for ip in iplist]
			subnets[group][group_name] = group_subnets
	return subnets, reserved