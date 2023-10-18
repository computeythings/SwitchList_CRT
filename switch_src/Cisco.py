'''
    A re-design of the original Cisco class. The intention behind this redesign is to make
    the code more scalable and consistent by getting initial inputs and consistently applying
    parsing methods to that output rather than changing input based on prior input.

    This also makes it easier to implement unit testing which has now also been added to this
    repository.

    The Cisco class should contain all necessary functions in order to scrape relevant info
    from Cisco network devices managed by 35 CS. This includes Cisco IOS-XE L2/L3 switches,
    Cisco ISR routers, and Cisco Nexus 5K devices.

    SrA Gonnella, Bryan
    17 OCT 2022
'''
import re, calendar, json, logging, os
from datetime import date
import IPUtils
log = logging.getLogger(__name__)

class Cisco:
    '''
        This class is initialized with kwargs to allow for easier re-initialization of pre-defined
        devices.
    '''
    def __init__(self, **kwargs):
        log.debug(f'%s: Initializing Cisco Switch','init')
        self.ip = ''
        self.make = 'Cisco'
        self.conn_type = ''
        self.privileged = True
        self.device_type = ''
        self.os_type = ''
        self.upstream_local = ''
        self.interfaces = {}
        self.ips = set()
        self.native_vlans = set()
        self.active_acls = set()
        self.keychains = {}
        self.acls = {}
        self.hostname = 'Switch'
        self.user_ports = 0
        self.uptime = '0 days 0 minutes 0 seconds'
        self.mac = []
        self.int_status_string = ''
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.prompt = self.hostname + ('#' if self.privileged else '>')

    '''
        Takes param command and sends the command to the switch in global mode.
        Should be mainly used for show commands.

        Takes optional param prompt and waits for that string before returning that value.
        Default prompt = the switch hostname + '#"
        ex. "CoreSwitch#"

        returns
            output from command up to prompt value as a string
    '''
    def send(self, command, prompt=''):
        # Using pre-defined test strings
        if self.conn_type == 'OFFLINE':
            # Commands are stored as string values with keys matching each command
            return self.conn[command]
        # Using SecureCRT
        if self.conn_type == 'CRT':
            log.debug(f'%s: Sending string: {command}', 'send')
            if prompt == '':
                prompt = self.prompt
            self.crtTab.Screen.Send('%s\r' % command)
            self.crtTab.Screen.WaitForString('\r\n') # ignore input line
            output = self.crtTab.Screen.ReadString(prompt, 5)
            if 'Invalid input' in output:
                log.warn(f'%s: {output}', 'send')
                raise ValueError(output)
            return output
        # Using Netmiko
        return self.conn.send_command(command)

    '''
        Takes param config_command which is formatted as a list of commands to be executed.
        Enters configuration mode before executing and returns to global mode after.

        Detects execution failures and raises Exception containing error information if a 
        command fails to execute and returns to global mode.

        returns
            response - list of outputs for each command
    '''
    def send_config(self, config_command):
        if isinstance(config_command, str):
            config_command = [config_command]
        response = []
        # If no commands are supplied or we or running offline testing
        if len(config_command) == 0 or self.conn_type == 'OFFLINE':
            return response
        prompt_old = self.prompt

        # Using Netmiko
        if self.conn_type == 'SSH':
            return self.conn.send_config_set(config_command).splitlines()

        # Using SecureCRT
        self.crtTab.Screen.Send('conf t\r')
        self.crtTab.Screen.WaitForString('\r\n')
        self.crtTab.Screen.WaitForString('\r\n')
        self.prompt = self.crtTab.Screen.ReadString('(').strip() + '('     
        for command in config_command:
            log.debug(f'%s: Running command on {self.hostname}: {command}', 'send_config')
            output = self.send(command)
            response.append(output)
            if 'Invalid input' in output:
                log.error(f'%s: Error sending command {command}', 'send_config')
                self.send('end')
                raise ValueError('UNSUPPORTED COMMAND')
        self.prompt = prompt_old
        self.send('end')
        return response

    def write_mem(self):
        log.info(f'%s: Writing config to NVRAM', 'write_mem')
        if self.conn_type == 'OFFLINE':
            return 'write mem simulated'
        if self.conn_type == 'CRT':
            if prompt == '':
                prompt = self.prompt
            self.crtTab.Screen.Send('write mem\r')
            self.crtTab.Screen.WaitForString('\r\n') # ignore input line
            output = self.crtTab.Screen.ReadString(prompt, 15)
            if 'Invalid input' in output:
                log.warn(f'%s: {output}', 'send')
                raise ValueError(output)
            return output
        # Using Netmiko
        return self.conn.send_command('write mem', read_timeout=150)
    '''
        Convert full port name to shorthand version used for compatibility between commands
        Takes @param
            port_name - full port name ex. "GigabitEthernet1/0/1"

        returns port shorthand name ex. "Gi1/0/1"
    '''
    def port_shorthand(self,port_name):
        return port_name.replace('AppGigabitEthernet', 'Ap').replace('FortyGigabitEthernet', 'Fo').replace('TwentyFiveGigE', 'Twe').replace('TenGigabitEthernet', 'Te').replace('GigabitEthernet', 'Gi').replace('FastEthernet', 'Fas').replace('Port-channel', 'Po')

    '''
        Takes an abbreviated port name and extends it to the full name
        Takes @param
            port_name - port shorthand name ex. "Gi/0/1"

        returns port long-form name ex. "GigabitEthernet1/0/1"
    '''
    def port_longform(self,port_name):
        return port_name.replace('Po','Port-channel').replace('Fa','FastEthernet').replace('Gi','GigabitEthernet').replace('Te','TenGigabitEthernet').replace('Twe','TwentyFiveGigE').replace('Fo','FortyGigabitEthernet').replace('Ap','AppGigabitEthernet')

    '''
        Gets the current running configuration and version info and saves them
        to class attributes as a base for future information parsing
    '''
    def readinfo(self):
        self.send('terminal length 0')
        log.debug(f'%s: Reading local info', 'readinfo')
        self.read_local()
        log.debug(f'%s: Reading neighbor info', 'readinfo')
        self.read_connected()

    '''
        Get information about this device
    '''
    def read_local(self):
        self.send('terminal length 0')
        config = self.send('show run')
        self.config = config.splitlines()
        ver_string = self.send('show version')
        self.ver_string = ver_string.splitlines()
        self.parse_version()
        if 'Switch' in self.device_type:
            mac_string = self.send('show mac address-table')
            self.mac_string = mac_string.splitlines()
        else:
            self.mac_string = ''
        if self.device_type == 'Nexus':
            arp_string = self.send('show ip arp')
        else:
            arp_string = self.send('show arp')
        self.arp_string = arp_string.splitlines()
        try:
            fipsstring = self.send('show fips status')
            self.fipsstring = fipsstring.splitlines()
            fipskeystring = self.send('show fips authorization-key')
            self.fipskeystring = fipskeystring.splitlines()
        except ValueError as e:
            log.warning(f'%s: Device {self.hostname} - {self.ip} does not support FIPS mode', 'read_local')
            self.fipsstring = 'N/A'
            self.fipskeystring = 'N/A'

    '''
        Gets information about connected neighbors
    '''
    def read_connected(self):
        # Only care about root ports devices on layer 2 devices
        if self.device_type == 'Switch':
            span_string = self.send('show spanning-tree root port')
            self.span_string = span_string.splitlines()
            self.ospf_string = ''
        # Read layer 3 info from routing-devices only
        else:
            ospf_string = self.send('show ip ospf neighbor')
            self.ospf_string = ospf_string.splitlines()
            self.span_string = ''
        if self.device_type == 'Nexus':
            route_string = 'show forwarding ip route 0.0.0.0/0'
        else:
            route_string = self.send('show ip cef 0.0.0.0/0')
        self.route_string = route_string.splitlines()
        cdp_string = self.send('show cdp neighbors detail')
        self.cdp_string = cdp_string.splitlines()

    def read_interface_status(self):
        if 'Switch' in self.device_type:
            self.int_status_string = self.send('show interfaces status')
        else:
            self.int_status_string = ''
        return self.int_status_string

    '''
        Takes param auth_config which contains all lines for authentication from an interface configuration.

        returns
            True if interface is configured with all mandatory authentication controls
    '''
    def validate_auth(self, auth_config):
        full_auth = {
            'authentication event fail retry 1 action next-method',
            'authentication host-mode multi-auth',
            'authentication order mab dot1x',
            'authentication priority dot1x',
            'authentication port-control auto',
            'authentication timer restart 5',
            'mab',
            'dot1x pae authenticator',
        }
        return auth_config == full_auth


    '''
        Takes param sc_config which contains all lines that begin storm-control from an interface configuration.

        returns
            True if configured storm-control values match defined values
    '''
    def validate_stormcontrol(self, sc_config):
        full_stormcontrol = {
            'storm-control broadcast level bps 1g',
            'storm-control unicast level bps 1g',
            'storm-control action shutdown'
        }
        return sc_config == full_stormcontrol

    '''
        Uses the self.config value to search for any key chain configurations.

        returns
            keychains - a dictionary containing key values, key start times, key end times, and algorithm type.
                Indexed by keychain name
                key start/end saved as date() objects

        ex:
        {
            'OSPF-KEYCHAIN' : {
                'active': True,
                'keys': {
                    '1': {
                        key_start: date(2022, 10, 22), #Oct 22 2022
                        key_end: date(2023, 1, 22), #Jan 22 2023
                        algorithm: 'hmac-sha-256'
                    }
                }
            }
        }
    '''
    def parse_keychains(self):
        log.debug(f'%s: Finding configured key chains', 'parse_keychains')
        keychains = {}
        current_keychain = ''
        current_key = ''
        for line in self.config:
            if line.startswith('key chain'):
                current_keychain = line.split()[-1]
                log.debug(f'%s: Found keychain {current_keychain}')
                current_key = ''
                keychains[current_keychain] = {'keys':{}}
            elif current_keychain != '' and line.startswith(' '):
                line = line.strip()
                if line.startswith('key '):
                    current_key = line.replace('key ','')
                    log.debug(f'%s: Found key {current_key} in keychain {current_keychain}', 'parse_keychains')
                    keychains[current_keychain]['keys'][current_key] = {
                        'algorithm': 'md5' # default algorithm is MD5
                    }
                elif line.startswith('accept-lifetime'):
                    split = line.split()
                    year = int(split[4])
                    day = int(split[3])
                    month = list(calendar.month_abbr).index(split[2])
                    keychains[current_keychain]['keys'][current_key]['key_start'] = date(year,month,day)
                    if 'infinite' in line:
                        keychains[current_keychain]['keys'][current_key]['key_end'] = 'infinite'    
                    else:
                        year = int(split[-1])
                        day = int(split[-2])
                        month = list(calendar.month_abbr).index(split[-3])
                        keychains[current_keychain]['keys'][current_key]['key_end'] = date(year,month,day)
                elif line.startswith('cryptographic-algorithm'):
                    keychains[current_keychain]['keys'][current_key]['algorithm'] = line.split()[-1]
            else:
                current_keychain = ''
                current_key = ''
        current_date = date.today()
        removekeys = []
        for keychain in keychains:
            for key in keychains[keychain]['keys']:
                end_date = keychains[keychain]['keys'][key]['key_end']
                if end_date == 'infinite':
                    continue
                if end_date < current_date:
                    removekeys.append(key)
        for key in removekeys:
            keychains[keychain]['keys'].pop(key)
        self.keychains = keychains
        return self.keychains
    

    '''
        Uses the self.ospf_string value to map all OSPF neighbors 
        
        returns 
            ospf_neighbors - a dictionary of all OSPF neihgbors on this device by port to neighbor IP address/RID

        ex: {
            'Gi1/1/1': {
                'neighbor_ip': '192.168.0.10', # Neighboring interface IP address
                'niehgbor_id': '192.168.0.10' # Neighbor's OSPF Router ID
            },
            'Vlan110': {
                'neighbor_ip': '192.168.2.2',
                'niehgbor_id': '2.2.2.2'
            }
        }
    '''
    def parse_ospf_neighbors(self):
        ospf_neighbors = {}
        for line in self.ospf_string:
            if 'FULL' in line:
                line_split = line.split()
                ospf_neighbors[line_split[-1]] = {
                    'neighbor_ip': line_split[-2],
                    'neighbor_id': line_split[0]
                }
        self.ospf_neighbors = ospf_neighbors
        return self.ospf_neighbors

    '''
        Uses the self.config value to serch for any interface configurations and stores relevant info into a dict.

        Interfaces are delineated by lines that no longer start with spaces as cisco defines sections with whitespace.

        returns
            interfaces - a dictionary keyed by interface containing values of all relevant information

        ex: 'GigabitEthernet1/0/1': {
            # line = "description EXAMPLE DESCRIPTION"
            'description': 'EXAMPLE DESCRIPTION', 
            # line = "ip address 192.168.1.1 255.255.255.0"
            'ip_address': '192.168.1.1', 
            # line = "ip address 192.168.1.1 255.255.255.0"
            'subnet': '255.255.255.0', 
            # line = "switchport mode access"
            'mode': 'access', 
            # line = "switchport access vlan 666"
            'access_vlan': '666', 
            # line = "switchport voice vlan 777"
            'voice_vlan': '777', 
            # line = "switchport trunk native vlan 999"
            'native_vlan': '999', 
            # line = "switchport trunk allowed vlan 123,456,789"
            'allowed_vlan': {'123',456',789'}, 
            # line = "switchport nonegotiate"
            'nonegotiate': True, 
            # line = "switchport block unicast" (global configuration line)
            'uufb': True, 
            # line = "ip arp inspection limit rate 100"
            'arp_limit': '100', 
            # verified against multiple lines to ensure all authentication commands exist (see function: validate_auth)
            'authentication': True, 
            # verified against multiple lines to ensure all storm-control commands exist (see function: validate_storm_control)
            'storm-control': True, 
            # line = "ip arp inspection trust"
            'dai_trust': True, 
            # line = "ip dhcp snooping trust"
            'dhcp_snooping_trust': True, 
            # line = "ip verify source"
            'ipsg': True, 
            # line = "auto qos trust cisco-phone"
            'auto_qos': 'voip cisco-phone', 
            # interface contains lines: "spanning-tree portfast","spanning-tree bpduguard enable","spanning-tree guard root"
            'spanning-tree': {'portfast','bpduguard enable','guard root'},
            # interface contains line: "shutdown"
            'shutdown': True
        }
    '''
    def parse_interfaces(self):
        interfaces = {}
        current_interface = ''
        storm_control = set()
        authentication = set()
        for line in self.config:
            if line.startswith('interface'):
                current_interface = line.split()[-1]
                log.debug(f'%s: Parsing interface {current_interface}', 'parse_interfaces')
                interfaces[current_interface] = {
                    'description': '',
                    'ip_address': '',
                    'subnet': '',
                    'port-channel_group':'',
                    'port-channel_protocol':'',
                    'port-channel_mode':'',
                    'acl_in': '',
                    'acl_out':'',
                    'vrf':'',
                    'dynamic_routing': '', # OSPF/BGP/EIGRP
                    'routing_auth': '', # STATIC/"Keychain_Name"
                    'mode': 'access' if 'Switch' in self.device_type else 'routed', # access/trunk/routed
                    'directed-broadcast': False,
                    'access_vlan': '1',
                    'voice_vlan': '1',
                    'native_vlan': '1',
                    'allowed_vlan': set(),
                    'nonegotiate': False,
                    'uufb': False,
                    'arp_limit': '',
                    'authentication': False,
                    'storm-control': False,
                    'dai_trust': False,
                    'dhcp_snooping_trust': False,
                    'ipsg': False,
                    'auto_qos': '',
                    'spanning-tree': set(),
                    'shutdown': False
                }
                if current_interface.startswith('Vlan'):
                    # save VLAN ID as allowed VLAN for VLAN interfaces
                    interfaces[current_interface]['allowed_vlan'].add(current_interface.replace('Vlan',''))
                    interfaces[current_interface]['mode'] = 'routed'
                continue
            if current_interface != '':
                if line.startswith(' '):
                    line = line.strip()
                    if line.startswith('storm-control'):
                        storm_control.add(line)
                        if len(storm_control) >= 3:
                            interfaces[current_interface]['storm-control'] = self.validate_stormcontrol(storm_control)
                            
                    elif line.startswith('authentication') or line.startswith('mab') or line.startswith('dot1x'):
                        authentication.add(line)
                        # if total authentication commands are greater than or equal to a full authentication config
                        if len(authentication) >= 8:
                            interfaces[current_interface]['authentication'] = self.validate_auth(authentication)

                    else:
                        if line.startswith('description'):
                            interfaces[current_interface]['description'] = line.replace('description ', '')

                        if line.startswith('auto qos '):
                            interfaces[current_interface]['auto_qos'] = line.replace('auto qos ', '')

                        if line.startswith('switchport mode '):
                            interfaces[current_interface]['mode'] = line.split()[-1]

                        if line.startswith('switchport access vlan '):
                            interfaces[current_interface]['access_vlan'] = line.split()[-1]

                        if line.startswith('switchport voice vlan '):
                            interfaces[current_interface]['voice_vlan'] = line.split()[-1]

                        if line.startswith('switchport trunk native vlan '):
                            native_vlan = line.split()[-1]
                            interfaces[current_interface]['native_vlan'] = native_vlan
                            if not native_vlan in self.native_vlans:
                                self.native_vlans.add(native_vlan)

                        if line.startswith('ip arp inspection limit rate '):
                            interfaces[current_interface]['arp_limit'] = line.split()[-1]

                        if line.startswith('switchport trunk allowed vlan ') or line.startswith('encapsulation dot1Q '):
                            interfaces[current_interface]['allowed_vlan'].update(line.split()[-1].split(','))

                        if line == 'switchport nonegotiate':
                            interfaces[current_interface]['nonegotiate'] = True

                        if line == 'switchport block unicast':
                            interfaces[current_interface]['uufb'] = True

                        if line == 'ip arp inspection trust':
                            interfaces[current_interface]['dai_trust'] = True

                        if line == 'ip dhcp snooping trust':
                            interfaces[current_interface]['dhcp_snooping_trust'] = True

                        if line == 'ip verify source':
                            interfaces[current_interface]['ipsg'] = True

                        if line == 'ip directed-broadcast':
                            interfaces[current_interface]['directed-broadcast'] = True

                        if line == 'no switchport' or line == 'no ip address':
                            interfaces[current_interface]['mode'] = 'routed'

                        if line.startswith('spanning-tree'):
                            interfaces[current_interface]['spanning-tree'].add(line.replace('spanning-tree ', ''))

                        if line.startswith('ip access-group'):
                            direction = line.split()[-1]
                            acl = line.split()[-2]
                            interfaces[current_interface][f'acl_{direction}'] = acl
                            self.active_acls.add(acl)

                        if line == 'shutdown':
                            interfaces[current_interface]['shutdown'] = True

                        if line.startswith('ip address'):
                            interfaces[current_interface]['mode'] = 'routed'
                            if self.device_type == 'Nexus':
                                ip_address = line.replace('ip address ','').split('/')[0]
                                subnet = IPUtils.cidr_to_mask(line.split('/')[-1])
                                interfaces[current_interface]['ip_address'] = ip_address
                                interfaces[current_interface]['subnet'] = subnet
                            else:
                                ip_address = line.split()[-2]
                                self.ips.add(ip_address)
                                subnet = line.split()[-1]
                                interfaces[current_interface]['ip_address'] = ip_address
                                interfaces[current_interface]['subnet'] = subnet
                                if subnet == 'dhcp':
                                    interfaces[current_interface]['ip_address'] = 'dhcp'
                                    interfaces[current_interface]['subnet'] = '0.0.0.0'
                            # If the IP address matches the IP used to login, save as the management IP
                            if ip_address == self.ip:
                                log.debug(f'%s: Found management IP interface: {current_interface}')
                                self.mgmt_interface = current_interface
                                self.subnet = subnet
                            else:
                                log.debug(f'%s: Interface {current_interface} IP {ip_address} {subnet} is not management')

                        if line.startswith('channel-group '):
                            if 'mode' in line:
                                group, mode = line.replace('channel-group ','').split(' mode ')
                            else:
                                group = line.split()[-1]
                                mode = 'lacp' # Default mode on 5Ks
                            interfaces[current_interface]['port-channel_group'] = group
                            interfaces[current_interface]['port-channel_mode'] = mode

                        if line.startswith('channel-protocol '):
                            interfaces[current_interface]['port-channel_protocol'] = line.replace('channel-protocol ','')

                        # Note: This scrip treats unencrypted ip ospf authentication-key as no routing auth because its as good as nothing
                        if line.startswith('ip ospf'):
                            interfaces[current_interface]['dynamic_routing'] = 'OSPF'
                            if 'message-digest-key' in line:
                                interfaces[current_interface]['routing_auth'] = 'STATIC'
                            if 'key-chain' in line:
                                key_chain = line.split()[-1]
                                if key_chain in self.keychains:
                                    self.keychains[key_chain]['active'] = True
                                else:
                                    log.warning(f'%s: Found un-mapped keychain on interface {current_interface}', 'parse_interfaces')
                                interfaces[current_interface]['routing_auth'] = key_chain

                        if line.startswith('ip vrf forwarding '):
                            interfaces[current_interface]['vrf'] = line.split()[-1]

                else:
                    log.debug(f'%s: Completed config for interface {current_interface}', 'parse_interfaces')
                    current_interface = ''
        self.interfaces = interfaces
        return self.interfaces

    '''
        Maps ACLs by name to a dict restriction compliances

        returns 
            acl - dict containing each ACL

        ex.
        {
            'EXTERNAL_ACL': {
                'config': [
                    {
                        'sequence_no': '10',
                        'permit': False,
                        'protocol': 'icmp',
                        'source': 'any',
                        'destination': 'any',
                        'match-type': 'fragments',
                        'log-type': 'log-input',
                        'self': False
                    },
                    ...
                ] # arry of ACE dicts (*see parse_ace() and parse_ace_standard())
                'restrict-to-self': True,
                'min-log-type': 'log-input', # none/log/log-input
                'explicit-deny-default': True # last line = 'deny ip any any'
            }
        }
    '''
    def parse_acl(self):
        acls = {}
        current_acl = ''
        for line in self.config:
            # standard access lists
            if line.startswith('access-list'):
                if current_acl == '':
                    current_acl = line.split()[1]
                    log.debug(f'%s: Reading through ACL {current_acl}', 'parse_acl')
                    acls[current_acl] = {
                        'extended': False,
                        'config': [],
                        'drop_icmpfrag': False,
                        'restrict-to-self': True,
                        'min-log-type': 'log',
                        'explicit-deny-default': False
                    }
                ace = self.parse_ace_standard(line)
                acls[current_acl]['config'].append(ace)
                if ace['source'] == 'any' and ace['permit']:
                    log.debug(f'%s: ACE "{line}" of {current_acl} allows unrestricted traffic to this device')
                    acls[current_acl]['restrict-to-self'] = False
            # named access lists
            elif line.startswith('ip access-list'):
                current_acl = line.split()[-1]
                extended = line.split()[-2] == 'extended'
                log.debug(f'%s: Reading through ACL {current_acl}', 'parse_acl')
                acls[current_acl] = {
                    'extended': extended,
                    'config': [],
                    'drop_icmpfrag': False,
                    'restrict-to-self': True,
                    'min-log-type': 'log-input' if extended else 'log',
                    'explicit-deny-default': False
                }
            elif line.startswith(' ') and current_acl != '':
                if 'remark' in line:
                    continue
                if acls[current_acl]['extended']:
                    ace = self.parse_ace(line)
                else:
                    ace = self.parse_ace_standard('access-list' + line)
                acls[current_acl]['config'].append(ace)
                if not ace['permit']:
                    if 'fragments' in ace['match-type']:
                        acls[current_acl]['drop_icmpfrag'] = True

                    if ace['log-type'] == 'log' and acls[current_acl]['min-log-type'] == 'log-input':
                            acls[current_acl]['min-log-type'] = 'log'
                    elif ace['log-type'] == '':
                        acls[current_acl]['min-log-type'] = 'none'
                # if the ACE is a permit ip any to a subnet this device is in, it does not restrict traffic to self
                elif ace['source'] == 'any' and ace['protocol'] == 'ip':
                    log.debug(f'%s: ACE "{line}" of {current_acl} allows unrestricted traffic to this device', 'parse_acl')
                    acls[current_acl]['restrict-to-self'] = False
                        
            else:
                current_acl = ''
        for acl in acls:
            if len(acls[acl]['config']) == 0:
                continue
            explicit_deny = not acls[acl]['config'][-1]['permit']
            any_source = acls[acl]['config'][-1]['source'] == 'any'
            any_dest = acls[acl]['config'][-1]['destination'] == 'any'
            if explicit_deny and any_source and any_dest:
                acls[acl]['explicit-deny-default'] = True
            else:
                # No explicit deny means implicitly denied packets are not logged
                acls[acl]['min-log-type'] = 'none'
        self.acls = acls
        return self.acls

    '''
        Reads an extended ACE (access control entry) into a map of all values for ACE

        ex. ace = "10 deny icmp any any fragments log-input"
        {
            'sequence_no': '10',
            'permit': False,
            'protocol': 'icmp',
            'source': 'any',
            'destination': 'any',
            'match-type': 'fragments',
            'log-type': 'log-input',
            'to_self': False,
            'from_self': False
        }
    '''
    def parse_ace(self, ace):
        log.info(f'%s: Parsing access control entry: {ace}', 'parse_ace')
        ace_dict = {
            'sequence_no': '',
            'permit': False,
            'protocol': '',
            'source': '',
            'destination':'',
            'match-type':'',
            'log-type':'',
            'to_self': False,
            'from_self': False
        }
        sections = ace.split()
        i = 0
        if sections[i] == 'permit' or sections[i] == 'deny':
            ace_dict['sequence_no'] = ''
        else:
            ace_dict['sequence_no'] = sections[i]
            i+= 1
        
        ace_dict['permit'] = sections[i] == 'permit'
        i+= 1

        ace_dict['protocol'] = sections[i]
        i+= 1

        if sections[i] == 'any':
            ace_dict['source'] = 'any'
            i+= 1
        else:
            ace_dict['source'] = ' '.join([sections[i],sections[i+1]])
            i+= 2

        if sections[i] == 'any':
            ace_dict['destination'] = 'any'
            i+= 1
        else:
            ace_dict['destination'] = ' '.join([sections[i],sections[i+1]])
            i+= 2

        filters = ''
        while i < len(sections):
            if not 'log' in sections[i]:
                filters = sections[i]
            else:
                ace_dict['log-type'] = sections[i]
            i+= 1
        ace_dict['match-type'] = filters
        for ip in self.ips:
            if not ace_dict['to_self']:
                ace_dict['to_self'] = IPUtils.ip_in_subnet(ip, *ace_dict['destination'].split())
            if not ace_dict['from_self']:
                ace_dict['from_self'] = IPUtils.ip_in_subnet(ip, *ace_dict['source'].split())
            if ace_dict['from_self'] and ace_dict['to_self']:
                break
        return ace_dict

    
    '''
        Reads a standard ACE into a map of all values for ACE
        
        ex. access-list 20 deny 192.168.0.0 0.0.0.255 log
    '''
    def parse_ace_standard(self, ace):
        ace_dict = {
            'sequence_no': '',
            'permit': False,
            'protocol': 'ip',
            'source': '',
            'destination':'any',
            'match-type':'',
            'log-type':'',
            'to_self': True,
            'from_self': False
        }
        sections = ace.split()
        ace_dict['permit'] = sections[2] == 'permit'
        i = 3
        source = []
        while i < len(sections) and not 'log' in sections[i]:
            source.append(sections[i])
            i+= 1
        ace_dict['source'] = ' '.join(source)
        if i < len(sections) and 'log' in sections[i]:
            ace_dict['log-type'] = sections[i]
        for ip in self.ips:
            if not ace_dict['from_self']:
                ace_dict['from_self'] = IPUtils.ip_in_subnet(ip, *ace_dict['source'].split())
            else:
                break
        return ace_dict

    '''
        Maps all line interfaces (vty, con, aux) to a map containing relevant values:

        ex.
        self.lines = {
            'vty': {
                '0-4' : {
                    'exec-timeout': 600,
                    'session-timeout': 600,
                    'input': {'ssh'},
                    'output': {'ssh'},
                    'acl': '',
                    'exec': True
                },
                '5-15' : {
                    'exec-timeout': 600,
                    'session-timeout': 600,
                    'input': {'none'},
                    'output': {'none'},
                    'acl': '',
                    'exec': False
                }
            },
            'con': {
                '0': {
                    'exec-timeout': 600,
                    'session-timeout': 600,
                    'input': {},
                    'output': {},
                    'acl': '',
                    'exec': True
                }
            }
        }
    '''
    def parse_lines(self):
        lines = {}
        current_line = ''
        current_range = ''
        for line in self.config:
            if line.startswith('line '):
                log.debug(f'%s: Parsing line string: {line}', 'parse_lines')
                line_info = line.replace('line ','').split()
                current_line = line_info[0]
                lines.setdefault(current_line,{})
                line_range = []
                try:
                    line_range.append(line_info[1])
                except:
                    log.error(f'%s: Unable to parse line: {line}', 'parse_lines')
                    current_line = ''
                    continue
                if len(line_info) > 2:
                    line_range.append(line_info[2])
                current_range = '-'.join(line_range)
                lines[current_line][current_range] = {
                    'exec-timeout': 600,
                    'session-timeout': 180,
                    'input': {'all'},
                    'output': {'all'},
                    'acl': '',
                    'exec': True
                }
            elif line.startswith(' ') and current_line != '':
                line = line.strip()
                if line.startswith('transport'):
                    io_allow = line.split()[1]
                    lines[current_line][current_range][io_allow] = set(line.split()[2:])
                elif line.startswith('session-timeout'):
                    try:
                        lines[current_line][current_range]['session-timeout'] = int(line.split()[-1])*60
                    except:
                        log.warning(f'%s: Unable to parse session timeout value: {line}', 'parse_lines')
                        lines[current_line][current_range]['session-timeout'] = line.split()[-1]
                elif line.startswith('exec-timeout'):
                    try:
                        minutes = int(line.split()[-2])
                        seconds = int(line.split()[-1])
                        lines[current_line][current_range]['exec-timeout'] = (minutes*60) + seconds
                    except:
                        log.warning(f'%s: Unable to parse exec timeout value: {line}', 'parse_lines')
                        lines[current_line][current_range]['exec-timeout'] = 9999
                elif line.startswith('access-class'):
                    lines[current_line][current_range]['acl'] = line.split()[-2]
                elif line == 'no exec':
                    lines[current_line][current_range]['exec'] = False
            else:
                current_line = ''
                current_range = ''
        log.debug(f'%s: Found all lines: {lines}', 'parse_lines')
        self.lines = lines
        return self.lines


    ''' 
        Maps all layer 2 entries keyed by MAC Address

        returns 
            mac_table - a dictionary of MAC addresses and their port/vlan/type

        ex.
        {
            '0420.6969.b00b': {
                'VLAN': '110',
                'TYPE': 'STATIC',
                'PORT': 'Gi1/0/1'
            }
        }
    '''
    def parse_mac_table(self):
        mac_pattern = re.compile('[0-9a-f]{4}.[0-9a-f]{4}.[0-9a-f]{4}')
        mac_table = {}
        for line in self.mac_string:
            if mac_pattern.search(line):
                if self.device_type == 'Nexus':
                    cols = line.split()
                    vlan = cols[1]
                    mac = cols[2]
                    type = cols[3]
                    port = cols[-1]
                else:
                    vlan,mac,type,port = line.split()
                mac_table[mac] = {
                    'VLAN': vlan.replace('Vl',''),
                    'TYPE': type, # 'STATIC' or 'DYNAMIC'
                    'PORT': port 
                }
        self.mac_table = mac_table
        return mac_table

    ''' 
        Maps all layer 3 entries keyed by IP Address

        returns 
            arp_table - a dictionary of ARP entries and their mac/port/etc.

        ex.
        {
            '192.168.1.1': {
                'PORT': '110' or 'Gi1/0/1', # Either VLAN ID or port value 
                'TYPE': 'ARPA',
                'MAC': '0420.6969.b00b',
                'AGE': '69',
                'PROTOCOL': 'Internet'
            }
        }
    '''
    def parse_arp_table(self):
        # Using the MAC address to match avoids pulling INCOMPLETE entries
        mac_pattern = re.compile('[0-9a-f]{4}.[0-9a-f]{4}.[0-9a-f]{4}')
        arp_table = {}
        for line in self.arp_string:
            if mac_pattern.search(line):
                proto,ip,age,mac,type,port = line.split()
                if 'Vlan' in port:
                    port = port.replace('Vlan', '')
                arp_table[ip] = {
                    'PORT': port, # ex. '110'
                    'TYPE': type, # ex. 'ARPA'
                    'MAC': mac, # ex. '0420.6969.b00b'
                    'AGE': age, # ex. '31' or '-'
                    'PROTOCOL': proto # ex. 'Internet'
                }
        self.arp_table = arp_table
        return arp_table

    '''
        Maps all VLAN IDs to their respective names

        returns
            vlans - a dictionary of VLAN ID:Name key value pairs
        ex.
        {
            '100' : 'USERS',
            '200' : 'PRINTERS',
            '300' : 'PHONES',
            '400' : '' # VLAN without a name
        }
    '''
    def parse_vlans(self):
        vlans = {}
        current_vlan = ''
        for line in self.config:
            if line.startswith('vlan'):
                # Handle lines that do not define vlans
                # ex. "vlan internal allocation policy ascending"
                if len(line.split()) > 2:
                    continue

                current_vlan = line.split()[-1]
                vlans[current_vlan] = ''

            elif line.strip().startswith('name'):
                vlans[current_vlan] = line.split()[-1]

        self.vlans = vlans
        return self.vlans

    '''
        Uses the self.config value to determine the swithces configured domain name.

        returns the domain name of the switch as string
    '''
    def parse_domain(self):
        log.debug(f'%s: Parsing switch domain...', 'parse_domain')
        for line in self.config:
            if line.startswith('ip domain name ') or line.startswith('ip domain-name'):
                self.domain = line.split()[-1]
                log.debug(f'%s: Found domain name: {self.domain}', 'parse_domain')
                return self.domain

    '''
        Uses the self.ver_string value which contains the full 'show version' output as a list split by line.
        Takes the "Cisco IOS Software" line present across all models and parses OS-type, version, model(s), and serial(s)

        returns (
            model - set of model values, 
            version - string value, 
            serial - set of serial values
        )
    '''
    def parse_version(self):
        serials = [] # multiple serials/models
        models = []
        line_number = 0
        for line in self.ver_string:
            if line.startswith('Cisco IOS Software'):
                info = line.split(',')
                os_str = info[0] # ex. "Cisco IOS Software [Gibraltar]" (excludes the [release] if not IOS-XE)
                type_str = info[1] # ex. "Catalyst L3 Switch Software (CAT3K_CAA-UNIVERSALK9-M)"
                ver_str = info[2] # ex. "Version 16.12.7"
                rel_str = info[3] # ex. "RELEASE SOFTWARE (fc2)"

                if 'VG' in type_str or 'ISR' in type_str:
                    self.device_type = 'Router'
                else:
                    self.device_type = 'Switch'
                    # Switch-RTR = L3 switch that does actual routing
                    if 'ip routing' in self.config:
                        self.device_type+= '-RTR'
    
                if os_str.endswith(']'):
                    self.os_type = 'IOS-XE'
                else:
                    if self.os_type == '':
                        self.os_type = 'IOS'
                self.version = ver_str.replace('Version ','').strip()
                self.version += ' %s' % rel_str.split()[-1]

            if 'NX-OS' in line:
                self.device_type = 'Nexus'
                self.os_type = 'NX-OS'
                ver_raw = self.send('show version | json')
                ver_json = json.loads(ver_raw)
                model = ver_json['chassis_id'].replace(' Chassis','') 
                version = ver_json['sys_ver_str']
                serial = ver_json['proc_board_id']
                self.model = [model]
                self.version = version
                self.serial = [serial]
                log.debug(f'%s: received info - Model: {self.model} | IOS: {self.version} | Serial: {self.serial}', 'get_version')
                return self.model, self.version, self.serial

            if self.device_type == 'Router':
                if line.upper().startswith('PROCESSOR BOARD ID '):
                    serials.append(line.split()[-1])
                    # The line prior to Processor board ID contains model as the second word
                    models.append(self.ver_string[line_number-1].split()[1]) 
            else:
                if line.upper().startswith('SYSTEM SERIAL'):
                    serials.append(line.split()[-1])
                if line.upper().startswith('MODEL NUMBER'):
                    models.append(line.split()[-1])
                    if '9606' in line.split()[-1]:
                        self.device_type+= '-RTR'

            if 'UPTIME' in line.upper():
                self.uptime = line.split(' is ')[-1].strip()
            if line.upper().startswith('BASE ETHERNET MAC ADDRESS'):
                macstring = line.split(': ')[-1].strip().replace(':','')
                macstring = '.'.join(re.findall('....', macstring)).lower()
                self.mac.append(macstring)
            line_number += 1
        self.serial = serials
        self.model = models
        # 9606R does not dispay the ip routing command in the standard show run config so it's not caught earlier
        if '9606R' in self.model:
            self.device_type+= '-RTR'
        return self.model, self.version, self.serial

    '''
        Uses the self.fipsstring and self.fipskeystring to identifiy if the device is 
        currently running in FIPS mode or is pending a reboot to enforce FIPS mode

        returns 
            fips - 'YES', 'NO', 'YES (ON REBOOT)
    '''
    def parse_fips(self):
        if self.device_type == 'Nexus':
            if 'disabled' in self.fipsstring:
                self.fips = 'NO'
            else:
                self.fips = 'YES'
            return self.fips
        else:
            if self.fipsstring == 'N/A':
                self.fips = 'N/A'
                return self.fips
            if not 'not' in self.fipsstring:
                self.fips = 'YES'
                return self.fips
            if not 'No key installed' in self.fipskeystring:
                self.fips = 'YES (ON REBOOT)'
                return self.fips
        self.fips = 'NO'
        return self.fips

    '''
        Uses the self.cdp_string value to segment and identify all CDP neighbors.
        Identifies upstream host and port matching port is found.
        returns
            cdp_neighbors - dict of all cdp neighbors mapped by port

        ex. 
        {
            'Gi1/1/1' : {
                'distant_host': 'QKKG-AN-EXAMPLE',
                'distant_port': 'Gi1/1/1',
                'distant_ip': '192.168.1.2'
            }
        }
    '''
    def parse_cdp(self):
        log.debug(f'%s: Parsing cdp neighbors...', 'parse_cdp')
        cdp = {}
        upstream_host = 'N/A'
        upstream_port_distant = 'N/A'
        upstream_ip = 'N/A'
        skip = False
        for line in self.cdp_string:
            line = line.strip()
            if line.startswith('---'):
                skip = False
                current_neighbor = ''
                local_port = ''
            if skip:
                continue
            if line.startswith('Device ID:'):
                current_neighbor = line.replace('Device ID:','').split('.')[0].strip()
                log.debug(f'%s: Found neighbor {current_neighbor}','parse_cdp')
                if current_neighbor.startswith('SEP'):
                    skip = True # skip phone
            if line.startswith('Interface:'):
                local_side, distant_side = line.split(',')
                local_port = local_side.split(':')[1].strip()
                cdp.setdefault(local_port, {})
                cdp[local_port]['distant_host'] = current_neighbor
                cdp[local_port]['distant_port'] = distant_side.split(':')[1].strip()
                # Check port match against upstream stripped of all SVI info (CDP neighbors appear on physical interfaces)
                upstream_check = self.upstream_local.split('.')[0]
                # Map port as upstream if the local port matches previously identified upstream port
                if  local_port in upstream_check.split(','):
                    log.info(f'%s: Found upstream on port {local_port}', 'parse_cdp')
                    upstream_host = current_neighbor
                    upstream_port_distant = cdp[local_port]['distant_port']
            if line.startswith('IP address:') and local_port != '':
                cdp.setdefault(local_port, {})
                cdp[local_port]['distant_ip'] = line.split()[-1]
                if local_port in upstream_check.split(','):
                    upstream_ip = cdp[local_port]['distant_ip']

        self.upstream_ip = upstream_ip                    
        self.upstream_host = upstream_host
        self.upstream_port_distant = upstream_port_distant
        self.cdp = cdp
        return self.cdp

    '''
        Checks spanning-tree for root port of the management VLAN.
        If spanning-tree is not running or this root is the bridge, upstream port is
        determined based on the default route.

        Pre-requisite: Your site must have an STP domain with the root bridge at the layer 2 boundary location

        returns
            upstream_local - string value of the local port that leads upstream
    '''
    def parse_upstream(self):
        upstream_local = ''
        # if the device is an older IOS layer 2 switch, use the less reliable spanning tree root port as the upstream
        if self.device_type == 'Switch' and self.os_type == 'IOS':
            if len(self.interfaces) == 0:
                self.parse_interfaces()
            vlanID = list(self.interfaces[self.mgmt_interface]['allowed_vlan'])[0]
            # pad vlan ID out to 4 values and prepend with "VLAN" ex. VLAN0010
            span_vlan = 'VLAN' + '0'*(4-len(vlanID)) + vlanID
            log.debug(f'%s: Searching for upstream port for {span_vlan}')
            for line in self.span_string:
                if line.startswith(span_vlan):
                    upstream_local = line.split()[-1]
                    self.upstream_local = upstream_local
                    log.debug(f'%s: Found local upstream port: {self.upstream_local}', 'parse_upstream')
                    return self.upstream_local
        outbound = []
        for line in self.route_string:
            if self.device_type == 'Nexus' and '0.0.0.0/0' in line:
                upstream = line.split()[-1]
                outbound.append(upstream)
            elif 'nexthop' in line:
                upstream = line.split()[-1] # line should be "nexthop <IP> <Upstream>"
                log.debug(f'%s: Found default route to {upstream}', 'parse_upstream')
                if 'Vlan' in upstream:
                    upstream_ip = line.split()[1] 
                    self.parse_mac_table()
                    self.parse_arp_table()
                    upstream_mac = self.arp_table[upstream_ip]['MAC']
                    upstream = self.mac_table[upstream_mac]['PORT']
                outbound.append(self.port_longform(upstream))
        self.upstream_local = ','.join(outbound)
        log.debug(f'%s: Found local upstream port: {self.upstream_local}')
        return self.upstream_local

    '''
        Reads through the status of all ports on device to attempt to find connected user ports
            returns 
                self.user_ports - the count of all active user ports
                (or 0 for the user ports if the device is not a switching device 
                as routers will have no user devices connected by policy)
    '''
    def parse_user_ports(self):
        if self.device_type == 'Router':
            return self.user_ports
        if self.int_status_string == '':
            self.read_interface_status()
        for line in self.int_status_string.splitlines():
            if not 'connect' in line:
                print(f'{line} not connected')
                continue
            port = line.split()[0]
            if 'connected' in line:
                self.interfaces[self.port_longform(port)]['connected'] = True
                if self.interfaces[self.port_longform(port)]['mode'] == 'access':
                    self.user_ports+= 1
            else:
                self.interfaces[self.port_longform(port)]['connected'] = False
        return self.user_ports

    '''
        A representation of the device type (excluding ports or model type)
    '''
    def base_model(self):
        print(f'Getting base model for {self.model[0]} with device {self.os_type}')
        base_model = self.model[0].split('-')[0]
        if base_model == 'WS':
            return base_model + '-' + self.model[0].split('-')[1]
        # Default return type - unknown if this will work but it's an attempt
        return base_model

    '''
        returns 
            data - a dict representation of this device
    '''
    def json(self):
        data = {
            'Hostname': self.hostname,
            'IP Address': self.ip,
            'Subnet Mask': self.subnet,
            'Make': self.make,
            'Model': self.model,
            'Firmware': '%s %s %s' % (self.os_type, self.version, self.device_type if self.device_type != 'Nexus' else ''),
            'Serial': self.serial,
            'Upstream': '%s %s' % (self.upstream_host, self.port_shorthand(self.upstream_port_distant)) if self.upstream_host != 'N/A' else 'Unavailable',
            'FIPS Mode': self.fips
        }
        return data

    '''
        JSON output compliant with new SwitchJS WebApp
    '''
    def json_web(self):
        device_ips = {}
        for interface in self.interfaces:
            if self.interfaces[interface]['ip_address'] != '':
                ip = self.interfaces[interface]['ip_address']
                if ip == 'dhcp':
                    device_ips['DHCP'] = {'interface': interface, 'vrf': self.interfaces[interface]['vrf']}
                    continue
                cidr = IPUtils.mask_to_cidr(self.interfaces[interface]['subnet'])
                device_ips[f'{ip}/{cidr}'] = {'interface': interface, 'vrf': self.interfaces[interface]['vrf']}
        data = {
            'scan_ip': self.ip,
            'base_subnet': self.subnet,
            'hostname': self.hostname,
            'ip_addresses': device_ips,
            'make': self.make,
            'model': self.model,
            'base_model': self.base_model(),
            'firmware': '%s %s %s' % (self.os_type, self.version, self.device_type if self.device_type != 'Nexus' else ''),
            'serial': self.serial,
            'upstream': self.upstream_local,
            'fips': self.fips,
            'neighbors': self.cdp,
            'updated': 0,
            'uptime': self.uptime,
            'users': self.user_ports,
            'base_mac': self.mac,
            'managed': True,
            'reachable': True
        }
        return data

    def writeout(self, directory):
        with open(directory + '\\sh_arp', 'w') as file:
            file.write('\n'.join(self.arp_string))
        with open(directory + '\\sh_cdp', 'w') as file:
            file.write('\n'.join(self.cdp_string))
        with open(directory + '\\sh_cef', 'w') as file:
            file.write('\n'.join(self.route_string))
        with open(directory + '\\sh_mac', 'w') as file:
            file.write('\n'.join(self.mac_string))
        with open(directory + '\\sh_run', 'w') as file:
            file.write('\n'.join(self.config))
        with open(directory + '\\sh_span', 'w') as file:
            file.write('\n'.join(self.span_string))
        with open(directory + '\\sh_ver', 'w') as file:
            file.write('\n'.join(self.ver_string))
        with open(directory + '\\sh_ospf', 'w') as file:
            file.write('\n'.join(self.ospf_string))
        jsonfile = directory + '\\%s - %s.json' % (self.ip, self.hostname)
        file.write(json.dump(vars(self)), jsonfile, indent=4)

    def save_offline(self, directory):
        outputs = {
            'device_type' : self.make.lower(),
            'show run' : self.send('show run'),
            'show version' : self.send('show version'),
            'show mac address-table' : self.send('show mac address-table'),
            'show ip arp' : self.send('show ip arp'),
            'show arp' : self.send('show arp'),
            'show fips status' : self.send('show fips status'),
            'show fips authorization-key' : self.send('show fips authorization-key'),
            'show spanning-tree root port' : self.send('show spanning-tree root port'),
            'show ip ospf neighbor' : self.send('show ip ospf neighbor'),
            'show forwarding ip route 0.0.0.0/0' : self.send('show forwarding ip route 0.0.0.0/0'),
            'show ip cef 0.0.0.0/0' : self.send('show ip cef 0.0.0.0/0'),
            'show cdp neighbors detail' : self.send('show cdp neighbors detail'),
            'show lldp neighbors detail' : self.send('show lldp neighbors detail'),
            'show interfaces status' : self.send('show interfaces status'),
            'show version | json' : self.send('show version | json'),
        }
        filepath = os.path.join(directory, f'{self.ip}.json')
        with open(filepath, "w", encoding='UTF-8') as outfile:
            json.dump(outputs, outfile, indent=2)
        
    '''
        Health check - confirm logged in
        Returns status of crtTab
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
        
                    