import re, logging, traceback, json, os
import IPUtils
log = logging.getLogger(__name__)

mabgroups = {
    2: 'TRANE',
    10: 'DATA',
    82: 'VTC',
    96: 'Taclane',
    98: 'Printer'
}

MABGROUPS = {
    'DATA': 'DATA',
    'VOICE': 'Phones',
    'VTC': 'VTC',
    'SERVER': 'Server',
    'HAIPE': 'Taclane',
    'PRINTER': 'Printer',
    'ICS': 'ICS',
    'NETMAN': 'NETMAN',
    'TRANE': 'TRANE',
    '1495_AMMO': '1495_AMMO'
}

class Brocade:
    def __init__(self, **kwargs):
        self.make = 'Brocade'
        self.lldp = {}
        self.ip = ''
        self.mac = []
        self.subnet = ''
        self.config = ''
        self.hostname = ''
        self.lldp_string = ''
        self.mgmt_interface = ''
        self.int_status_string = ''
        self.uptime = '0 days 0 minutes 0 seconds'
        
        for key, value in kwargs.items():
            setattr(self, key, value)
        if not 'hostname' in kwargs:
            self.get_hostname()
        if 'SSH@' in self.hostname:
            self.hostname = self.hostname.replace('SSH@','')

    def readinfo(self):
        self.read_local()
        self.read_connected()
        self.read_interface_status()

    def parse_all(self):
        self.parse_ip()
        self.parse_gateway()
        self.parse_arp()
        self.parse_lldp()
        self.parse_user_links()

    '''def readinfo(self):
        self.get_serial()
        self.get_mask()
        self.get_version()
        self.get_gateway()
        self.get_subnet_mask()
        self.get_trunks()
        self.get_upstream()
        self.get_uptime()
        self.get_user_links()
        self.get_base_mac()'''

    def send(self, command, prompt=''):
        # Using pre-defined test strings
        if self.conn_type == 'OFFLINE':
            # Commands are stored as string values with keys matching each command
            if command in self.conn:
                return self.conn[command]
            return 'Unsupported'
        # Using SecureCRT
        if self.conn_type == 'CRT':
            log.debug(f'%s: Sending string: {command}', 'send')
            if prompt == '':
                prompt = self.prompt
            self.crtTab.Screen.Send('%s\r' % command)
            self.crtTab.Screen.WaitForString('\r\n') # ignore input line
            output = self.crtTab.Screen.ReadString(prompt, 5)
            if 'Invalid input' in output:
                log.warning(f'%s: {output}', 'send')
                raise ValueError(output)
            return output
        # Using Netmiko
        return self.conn.send_command(command)
        
    '''
        Health check - confirm logged in
        Returns status of SecureCRT crtTab or Netmiko conn
    '''
    def connected(self):
        # Simulate connected at all times when in offline-mode
        if self.conn_type == 'OFFLINE':
            return True
        if self.conn_type == 'CRT':
            return self.crtTab.connected
        return self.conn.is_alive()
        
    '''
        Disconnect current session
    '''
    def disconnect(self):
        if self.conn_type == 'OFFLINE':
            return True
        if self.conn_type == 'CRT':
            return self.crtTab.Session.Disconnect()
        return self.conn.disconnect()
    
    def get_hostname(self):
        if self.conn_type == 'OFFLINE':
            return self.parse_ip()
        self.crtTab.Screen.Send('skip-page-display\r')
        self.crtTab.Screen.WaitForString('SSH@')
        hostname = self.crtTab.Screen.ReadString('#').strip()
        self.hostname = hostname
        self.prompt = 'SSH@' + hostname + '#'
        return hostname

    '''
        Get information about this device
    '''
    def read_local(self):
        self.send('skip-page-display')
        config = self.send('show run')
        self.config = config.splitlines()
        ver_string = self.send('show version')
        self.ver_string = ver_string.splitlines()
        self.parse_version()
        mac_string = self.send('show mac-address')
        self.mac_string = mac_string.splitlines()
        arp_string = self.send('show arp')
        self.arp_string = arp_string.splitlines()

    '''
        Gets information about connected neighbors
    '''
    def read_connected(self):
        lldp_string = self.send('show lldp neighbors detail')
        self.lldp_string = lldp_string.splitlines()

    '''
        Gets information about local ports
    '''
    def read_interface_status(self):
        self.int_status_string = self.send('show interfaces brief').splitlines()
        return self.int_status_string

    '''
        Gets uptime, serial, model, and firmware of this device from the version string
    '''
    def parse_version(self):
        models = []
        serials = []
        uptime = ''
        firmware = ''
        for line in self.ver_string:
            if line.strip().startswith('HW'):
                models.append(line.split()[-1])
            if line.strip().startswith('SW'):
                firmware = line.split()[-1]
            if 'uptime' in line:
                # example "device uptime is 1 day(s) 2 hour(s) 6 minute(s)"
                # save everything after " is " and remove parentheses
                uptime = line.strip().split(' is ')[-1].replace('(s)','s')
            if line.strip().startswith('Serial'):
                serials.append(line.split(':')[1].strip())
        self.model = models
        self.base_model = self.model[0].split('-')[0]
        self.serial = serials
        self.uptime = uptime
        self.firmware = firmware
    
    '''
        Gets the IP and subnet mask of this device
        Gets hostname if found
    '''
    def parse_ip(self):
        for line in self.config:
            if line.startswith('ip address'):
                self.subnet = line.split()[-1]
                self.ip = line.split()[-2]
            if line.startswith('hostname'):
                hostname = line.split()[-1]
                self.hostname = hostname.split('.')[0]
    '''
        Searches the running config for the default gateway
        example line: "default-gateway  192.168.0.1 1"
    '''
    def parse_gateway(self):
        for line in self.config:
            if 'default-gateway' in line:
                self.gateway = line.split()[-2]
                return self.gateway
        return ''

    '''
        Since all Brocades are L2, we can use arp to determine the management VLAN
        as well as find the port leading to the CN as this is the only VLAN that ARP
        entries will exist on.
    '''
    def parse_arp(self):
        mgmt_interface = ''
        for line in self.arp_string:
            if 'Dynamic' in line:
                cols = line.split()
                ip = cols[1]
                port = cols[-3]
                vlan_id = cols[-1]
                self.vlan_id = vlan_id
                mgmt_interface = f'Vlan{vlan_id}'
                if ip == self.gateway:
                    self.upstream_local = port
        self.mgmt_interface = mgmt_interface

    '''
        Uses the self.lldp_string value to segment and identify all LLDP neighbors.
        Identifies upstream host and port matching port is found.
        returns
            lldp_neighbors - dict of all lldp neighbors mapped by port

        ex. 
        {
            'Gi1/1/1' : {
                'distant_host': 'QKKG-AN-EXAMPLE',
                'distant_port': 'Gi1/1/1',
                'distant_ip': '192.168.1.2'
            }
        }
    '''
    def parse_lldp(self):
        lldp = {}
        upstream_host = 'N/A'
        upstream_port_distant = 'N/A'
        for line in self.lldp_string:
            line = line.strip()
            if line.startswith('Local port: '):
                local_port = line.split()[-1]
            if line.startswith('+ Port ID'):
                # line example: + Port ID (interface name): "Gi1/0/12"
                # remove quotation marks when saving port ID
                distant_port = line.split()[-1].replace('"','')
            if line.startswith('+ System name'):
                # save hostname and remove quotes
                distant_host = line.split()[-1].replace('"','')
                # remove FQDN suffix
                distant_host = distant_host.split('.')[0]
            if line.startswith('+ Management address'):
                distant_ip = line.split()[-1]
            # Only save port if it is a trunk (i.e. assigned to dead VLAN 999)
            if line.startswith('+ Port VLAN ID:') and line.endswith('999'):
                lldp.setdefault(local_port, {})
                lldp[local_port]['distant_host'] = distant_host
                lldp[local_port]['distant_port'] = distant_port
                lldp[local_port]['distant_ip'] = distant_ip
                if local_port == self.upstream_local:
                    upstream_port_distant = distant_port
                    upstream_host = distant_host

        self.upstream_host = upstream_host
        self.upstream_port_distant = upstream_port_distant
        self.lldp = lldp
        return self.lldp

    '''
        Reads connected status of all local interfaces and subtracts
        the number of trunks to get all connected user ports.
        Also saves the device's Base MAC if found.
    '''
    def parse_user_links(self):
        trunks = len(self.lldp.keys())
        if trunks == 0:
            self.parse_lldp()
        linkcount = 0
        for line in self.int_status_string:
            if line.startswith('mgmt'):
                self.mac.append(line.split()[-1])
                continue
            if 'Up' in line:
                linkcount+= 1
        self.user_ports = linkcount - trunks
        if self.user_ports < 0:
            self.user_ports = 0
        return self.user_ports
        
    '''
        Save info as a backup string
    '''
    def backup(self):
        backup = self.send('sh run')
        backup += self.send('sh lldp ne de')
        backup += self.send('sh ip int')
        backup += self.send('sh interface lag')
        backup += self.send('sh int br')
        backup += self.send('sh ip ospf ne')
        self.backup = backup
        return backup

    '''
        Save info for use in testing
    '''
    def save_offline(self, directory):
        outputs = {
            'show run' : self.send('show run'),
            'show version' : self.send('show version'),
            'show mac-address' : self.send('show mac-address'),
            'show arp' : self.send('show arp'),
            'show lldp neighbors detail' : self.send('show lldp neighbors detail'),
            'show interfaces brief' : self.send('show interfaces brief'),
        }
        filepath = os.path.join(directory, f'{self.ip}.json')
        with open(filepath, "w", encoding='UTF-8') as outfile:
            json.dump(outputs, outfile, indent=2)

    def json(self):
        data = {
            'Hostname': self.hostname,
            'IP Address': self.ip,
            'Subnet Mask': self.subnet,
            'Make': self.make,
            'Model': self.model,
            'Firmware': self.firmware,
            'Serial': self.serial,
            'Upstream': 'Unavailable',
            'FIPS Mode': 'N/A'
        }
        return data

    def json_web(self):
        device_ips = {}
        cidr = IPUtils.mask_to_cidr(self.subnet)
        device_ips[f'{self.ip}/{cidr}'] = {'interface': self.mgmt_interface, 'vrf': ''}
        data = {
            'scan_ip': self.ip,
            'base_subnet': self.subnet,
            'hostname': self.hostname,
            'ip_addresses': device_ips,
            'make': self.make,
            'model': self.model,
            'base_model': self.base_model,
            'firmware': self.firmware,
            'serial': self.serial,
            'upstream': self.upstream_local,
            'fips': 'N/A',
            'neighbors': self.lldp,
            'updated': 0,
            'uptime': self.uptime,
            'users': self.user_ports, 
            'base_mac': self.mac,
            'managed': True,
            'reachable': True
        }
        return data
    

    '''
##########################################################################################################################

    ALL CODE BELOW SHOULD BE CONSIDERED DEPRECATED

##########################################################################################################################
    '''

    '''
        Returns Dict of pattern:
        {
            "110" : "DATA",
            "130" : "VOICE",
            ...,
        }
    '''
    def get_vlans(self):
        vlans = self.send('sh vlan | i ^PORT-VLAN')
        for vlan in vlans.splitlines():
            sections = vlan.split()
            vlan_id = sections[1].replace(',','')
            vlan_name = sections[3].replace(',','').upper()
            if vlan_id == '999' or vlan_id == '666' or vlan_id == '5':
                continue # these are standard and will be always added regardless
            vlans[vlan_id] = vlan_name
        self.vlans = vlans
        return self.vlans
        
    def get_port_vlans(self, port):
        # pull list of vlans on port
        vlan_string = self.send('sh vlan br e %s' % port).replace('VLANs ','')
        vlans = vlan_string.strip().split()
        return vlans
        
    def get_interfaces(self, desc=False):
        intlines = self.send('sh run int').splitlines()
        configured = {}
        index = 0
        while index < len(intlines):
            line = intlines[index]
            intconfig = []
            if 'interface management' in line:
                while line != '!':
                    index += 1
                    line = intlines[index]
            if 'interface ethernet' in line:
                name = line[line.rindex(' '):].strip()
                while line != '!':
                    intconfig.append(line.strip())
                    index += 1
                    line = intlines[index]
                if self.non_standard(intconfig):
                    configured[name] = {
                        'CONF': intconfig,
                        'VLANs': self.get_port_vlans(name)
                    }
            index += 1
        self.conf_int = configured
        return self.conf_int
        
    def non_standard(self, interface):
        description = ''
        for line in interface:
            if 'port-name' in line:
                description = line[line.index(' '):].strip()
        if 'taclane' in description.lower():
            return True
        if 'dot1x port-control auto' in interface:
            return False # dot1x means it's a standard port
        if 'spanning-tree 802-1w admin-pt2pt-mac' in interface:
            return False # this interface should already be accounted for in the trunks list
        if 'disable' in interface:
            return False # only trunks should be disabled and this is in the default config
        return True

    # get all mab devices except for phones
    def get_mab(self):
        failed = {}
        mab = {}
        mabskip = ['5','666','777','999']
        if not self.vlans:
            self.get_vlans()
        if not self.conf_int:
            self.get_interfaces()
        if not self.trunks:
            self.get_trunks()

        dot1x_devices = []
        lines = self.send('sh dot1x sess all | i AUTH')
        for line in lines.splitlines():
            log.debug(f'%s: Found dot1x devices {line.split()[1]}', 'get_mab')
            dot1x_devices.append(line.split()[1])
        lines = self.send('show mac-address | e MAC-Address|Total active entries')
        for line in lines.splitlines():
            device = line.split()
            mac = device[0]
            port = device[1]
            vlanID = device[4]
            if port in self.trunks:
                log.debug(f'%s: Skipping {mac} on {port} (trunk)','get_mab')
                continue
            if mac in dot1x_devices:
                log.debug(f'%s: Skipping {mac} on {port} (dot1x device)','get_mab')
                continue
            if vlanID in mabskip:
                log.debug(f'%s: Skipping {mac} on {port} (Dead VLAN)','get_mab')
                continue
            try:
                vlan_name = self.vlans[vlanID]
                if vlan_name == 'DATA':
                    continue
                # add a mac address if it's not already in the MAB list or overwrite existing if it's a phone
                if not mac in mab or vlanID.endswith('30'):
                    mab[mac] = {'MACAddress': mac,'EndPointPolicy':'','IdentityGroup':MABGROUPS[vlan_name], 'Description':''}
                    log.debug(f'%s: Added MAC Address {mac} to mab group {MABGROUPS[vlan_name]}','get_mab')
            except:
                # MAB group doesn't exist
                log.warning(f'%s: Unable to find MAB group for MAC {mac} on port {port} VLAN: {vlanID}', 'get_mab')
                log.error(f'%s: {traceback.print_exc()}', 'get_mab')
                mab[mac] = {'MACAddress': mac,'EndPointPolicy':'','IdentityGroup':'UNKNOWN_%s' % vlanID, 'Description':''}
                failed[mac] = {'VLAN':vlanID, 'PORT':port}
        self.mab = mab
        self.mab_manual = failed
        return mab, failed
        
    def get_int_downtime(self):
        list_downtime = self.send('sh int | i Port (up|down) for|line protocol is\r')
        int_pattern = re.compile('^.*Ethernet ?[0-9]\/[0-9]\/[0-9]?[0-9]')
        int_down = []
        i = 0
        downtimes = list_downtime.splitlines()
        while i < len(downtimes):
            line = downtimes[i]
            if 'Ethernet' in line:
                # lines that start with spaces are separate lanes in a aggregated module
                if not line.startswith(' ') and 'line protocol is down' in line: 
                    try:
                        interface = int_pattern.search(line).group(0)
                    except:
                        i+=2
                        continue
                    i+=1
                    line = downtimes[i]
                    start = line.index('Port down for ') + len('Port down for ')
                    downtime = line[start:]
                    i+=1
                    int_down.append({'interface':interface,'downtime':downtime})
                    continue
            i+=1
        self.downtimes = int_down
        return int_down