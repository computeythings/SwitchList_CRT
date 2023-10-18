import yaml, os, argparse, traceback
import SwitchMap

def setup():
    config = {'scan':{},'reserved':{}}
    new_data = config['scan']
    netgroup = input(
        '\nEnter a network name - This will be used as a sheet name in the excel file\n'
        '(Leave blank to finish)\n'
        'Name: '
    )
    while netgroup != '':
        if len(new_data) == 0:
            subnet = input(
                '\nEnter a subnet address in either CIDR notation, an IP range, or a single IP address\n'
                'ex. 192.168.0.0/24 or 192.168.1.30-192.168.1.50 or 192.168.2.1\n'
                '(Leave blank to finish)\n'
                'Address: '
            )
        else:
            subnet = input('Address: ')
        new_data.setdefault(netgroup, {})
        while subnet != '':
            if len(new_data) == 0:
                network_name = input('\nEnter full name to label this subnet (this is used as a title for the network address):\nSubnet Name: ')
            else:
                network_name = input('Subnet Name: ')
            new_data[netgroup].setdefault(network_name,[]).append(subnet)
            subnet = input('Address: ')
        netgroup = input('\n(Leave blank to end)\nEnter another network name: ')
    
    if 'Y' in input('Reserve IP addresses?\n(Y/N): ').upper():
        reserve_addr = 'init'
    else:
        reserve_addr = ''
        
    while True:
        reserve_addr = input('Reserve IP Address: ')
        if reserve_addr == '':
            break
        config['reserved'].update(add_reserved(reserve_addr))

    return config
        
def add_reserved(ip):
    while True:
        hostname = input('Enter device hostname:\n')
        subnet_mask = input('Enter device subnet mask:\n')
        make = input('Enter device manufacturer:\n')
        model = input('Enter device model (separate multiple models by spaces if stacked):\n')
        serial = input('Enter device serial (separate multiple serials by spaces if stacked):\n')
        firmware = input('Enter device firmware version:\n')
        fips = input('Is the device running in FIPS mode? (YES/NO):\n')
        reserved = {
            ip: {
                'Hostname': hostname,
                'Subnet Mask': subnet_mask,
                'Make': make,
                'Model': model.split(' '),
                'Serial': serial.split(' '),
                'Firmware': firmware,
                'FIPS Mode': fips
            }
        }
        reserved_string = '\n'.join([f'{key}:\t{value}' for  key, value in reserved[ip].items()])

        print('------------------------------\n')
        confirmed = input(f'CONFIRM DEVICE {ip}: \n\n{reserved_string}\n(Y/N):')
        if confirmed:
            return reserved
        
def get_value(prompt):
    sheet = ''
    while sheet.strip() == '':
        sheet = input(prompt)
    return sheet
'''
    Update existing config data or manually setup a new config
'''
def update(args):
    # Pull existing config data from file if exists
    config = {}
    if os.path.isfile(args.scanfile):
        try:
            with open(args.scanfile, 'r') as scanfile:
                config = yaml.safe_load(scanfile)
        except:
            # End if supplied file is not valid YAML
            return print(f'Unable to read file {args.scanfile}\n{traceback.print_exc()}')
    config.setdefault('scan',{})
    config.setdefault('reserved',{})
    
    # Load in sheet/group
    group_all = ''
    if args.group:
        group_all = ' '.join(args.group)
    sheet_all = ''
    if args.sheet:
        sheet_all = ' '.join(args.sheet)
    # If a group exists but a sheet doesn't then search for the value in existing config
    elif group_all != '':
        for sheet in config.get('scan',{}):
            if group_all in sheet:
                sheet_all = sheet
        # If group does not exist already, prompt for sheet to put it in now
        if not sheet_all:
            sheet_all = get_value(f'Sheet name for group {group_all}:')
    # Set defaults
    if sheet_all:
        config['scan'].setdefault(sheet_all,{}).setdefault(group_all,{})

    # Store reserved addresses
    if args.reserve:
        for ip in args.reserve:
            config['reserved'].update(add_reserved(ip))
            # If a group has been specified, add this IP to that group if it doesn't already exist there
            if group_all != '':
                existing_subnets = config['scan'][sheet_all][group_all]
                if not ip in SwitchMap.parse_list(existing_subnets):
                    existing_subnets.append(ip)

    # Add requested subnets - prompt for new sheet/group for each subnet if groupall does not exist
    for subnet in args.add:
        sheet = get_value(f'Sheet name for {subnet}')
        group = get_value(f'Group name for {subnet}')
        config['scan'][sheet][group].append(subnet)
    return config


def main():
    parser = argparse.ArgumentParser(description='Build a scan.yml file for the switchlist_generator script')
    parser.add_argument('scanfile', help='Device to run STIG checklists against')
    parser.add_argument('-r','--reserve',help='Reserve the supplied IP address', nargs='+')
    parser.add_argument('-g','--group',help='Specify a group to add subnets to', nargs='+')
    parser.add_argument('-s','--sheet',help='Specify a sheet to add subnets to', nargs='+')
    parser.add_argument('-a','--add',help='Specify a list of subnets to add', nargs='+',default=[])
    parser.add_argument('--setup',action='store_true',help='Guided setup process')
    args = parser.parse_args()

    if args.setup:
        config = setup()
    else:
        config = update(args)

    # Write data to file
    with open(args.scanfile, 'w') as outfile:
        yaml.safe_dump(config, outfile)
    

if __name__ == "__main__":
    main()