'''
	The Switch module API is an interface to initiate connections and return a
	usable Object containing the relevant functions to pull information. This module
	and all scripts uitlizing it are only meant to be used for Cisco and Brocade 
	network devices and are tailored specifically to the needs of the 35 CS/SCOI 
	at Misawa AB.

	A1C Gonnella, Bryan
	12 APRIL 2021
'''
import SecureCRT

import os, sys, logging, subprocess
local_path = os.path.dirname(os.path.realpath(__file__)) # gets full local directory path
sys.path.insert(1, local_path) # this sets the import path to the local directory
from Cisco import Cisco
from Brocade import Brocade

prompts = ['#','>']

def info_prompt():
	username = crt.Dialog.Prompt('Enter your username:', 'SSH User')
	password = crt.Dialog.Prompt('Enter your password:', 'SSH Password','', isPassword=True)
	return username, password

#	This will ping the device before attempting to connect to save time waiting for SSH timeouts
def host_online(ip):
	try:
		output = subprocess.check_output("ping -n 1 -w 1 %s" % ip, shell=True, universal_newlines=True)
		if 'unreachable' in output:
			logging.info('%s offline' % ip)
			return False
		else:
			return True
	except Exception as e:
			logging.info('%s offline' % ip)
			return False
	
#	SSH connections are initiated through SecureCRT which allows IA-approved execution of Python scripts
#	through a pre-compiled library embedded in the application
def ssh_connect(crt, username, password, host):
	# These are command line switches for SecureCRT. If you need more options, search for SecureCRT cli options
	cmd = '/SSH2 /L %s /PASSWORD %s %s /AcceptHostKeys' % (username, password, host)
	return crt.Session.ConnectInTab(cmd, True, False)

#	Returns a switch Object based on the prompt recieved on successful SSH login
def switch_init(crtTab, host):
	crtTab.Screen.Synchronous = True
	hostname = crtTab.Screen.ReadString(prompts, 5).split()[-1]
	logging.debug('Grabbed hostname %s' % hostname)
	if 'SSH@' in hostname:
		logging.debug('Found Brocade switch', 'Switch.switch_init')
		return Brocade(crtTab=crtTab, conn_type='CRT', ip=host)
	prompt_char = prompts[crtTab.Screen.MatchIndex - 1]
	logging.debug('Prompt char %s' % prompt_char)
	if prompt_char == '#':
		logging.debug('Found Cisco switch', 'Switch.switch_init')
		return Cisco(crtTab=crtTab, conn_type='CRT', ip=host, hostname=hostname)

	if prompt_char == '>':
		logging.debug('Found Cisco switch', 'Switch.switch_init')
		logging.warn('Cisco switch %s in non-privileged mode.' % host, 'Switch.switch_init')
		return Cisco(crtTab=crtTab, conn_type='CRT', ip=host, hostname=hostname, privileged=False)

	logging.error('Unable to initialize switch for IP: %s' % host, 'Switch.switch_init')
	return None
		
#	Callable function for use by external modules
def connect(crtSession, username, password, host, ignore_ping=False):
	logging.info('Connecting to device %s' % host, 'Switch.connect')
	if ignore_ping:
		logging.debug('Ignoring device online check.', 'Switch.connect')
	if ignore_ping or host_online(host):
		tab = ssh_connect(crtSession, username, password, host)
		return switch_init(tab, host)
	logging.warn('Host %s offline' % host, 'Switch.connect')
	return None