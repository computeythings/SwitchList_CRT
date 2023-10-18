'''
    The proper implementation of the Switch.py module - i.e. handled within
    Python entirely, does not rely on SecureCRT.

    This module requires the installation of the netmiko package.
    This is likely going to be run as part of a pre-packaged .exe file
    to prevent burdening NIPR users with the install of PIP packages 
    (PyPI is not trusted on NIPR and cannot be easily used from the CLI.)

    SrA Gonnella, Bryan
    7 NOV 2022
'''
import json, logging, os
from .Cisco import Cisco
from .Brocade import Brocade
logger = logging.getLogger(__name__)
class Offline:
    def __init__(self, directory):
        # local directory storing all device info
        self.directory = directory

    def info_prompt(self):
        return '',''
    def host_online(self, ip):
        return True

    '''
        Pulls device info from YAML file stored in device location
        returns a dictionary that includes the device_type as the device make
            as well as all pre-definied commands as keys with their outputs stored
            as corresponding string values
    '''
    def get_device_info(self, host):
        host_info = {}
        with open(os.path.join(self.directory, f'{host}.json'), 'r') as hostfile:
            host_info = json.load(hostfile)
        return host_info

    # Returns a switch Object based on the prompt recieved on successful SSH login
    def init(self, host):
        device_info = self.get_device_info(host)
        device = {
            'ip': host, 
            'conn': device_info, 
            'conn_type':'OFFLINE'
        }
        if 'device_type' in device_info:
            device_type = device_info['device_type']
            if 'brocade' in device_type:
                logger.debug('%s: Found Brocade switch', 'init')
                return Brocade(**device)
            if 'cisco' in device_type:
                logger.debug('%s: Found Cisco switch', 'init')
                return Cisco(**device)                
        else:
            # Forgot to add 'device_type' to Brocade output
            return Brocade(**device)
        logger.error(f'%s: Unhandled device type: {device_type}', 'init')
        return None
            
    # Callable function for use by external modules
    def connect(self, username, password, host, brand='', ignore_ping=False):
        logger.info(f'%s: Pulling offline configs for device: {host}', 'connect')
        return self.init(host)