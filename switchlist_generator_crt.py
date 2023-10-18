# $language = "python"
# $interface = "1.0"
import SecureCRT

import logging, os, yaml, json, csv, traceback
from SwitchList import SwitchMap
from switch_src import Switch as SSH


'''
    Import supplied YAML config into a readable dict
'''
def yaml_import(readfile):
    if readfile == '' or not os.path.exists(readfile):
        return {}
    logging.info('Pulling scan info from %s' % readfile, 'yaml_import')
    with open(readfile, 'r') as listfile:
        scanlist = yaml.safe_load(listfile)
    return scanlist

def main():
    # CLI argument init
    scanfile = crt.Dialog.FileOpenDialog("Scan file","Open",filter="YAML files (*.yml)|*.yml|*.yaml||")
    outdir = "\\".join(scanfile.split("\\")[:-1])
    logfile = "%s\\switchlist.log" % outdir
    jsonfile = "%s\\switches.json" % outdir
    csvfile = "%s\\switches.csv" % outdir

    # Logging setup
    logmap = [logging.ERROR,logging.WARNING,logging.INFO,logging.DEBUG]
    logging.Formatter('%(asctime)s %(levelname)s:%(message)s')
    log_args = {'level':logmap[2]}
    log_args['filename'] = logfile
    log_args['filemode'] = 'w'
    logging.basicConfig(**log_args)

    # Load pre-scanned switches
    current_switches = {}
    try:
        with open(jsonfile, 'r') as jsonlist:
            current_switches = json.load(jsonlist)
    except:
        logging.warning('File %s does not exist.' % os.path.abspath(jsonfile), 'main')
    
    # Load YAML configuration file
    scan_list = {}
    if scanfile:
        try:
            if scanfile == '' or not os.path.exists(scanfile):
                return {}
            logging.info('Pulling scan info from %s' % scanfile, 'main')
            with open(scanfile, 'r') as configfile:
                config = yaml.safe_load(configfile)

            scan_list, reserved = SwitchMap.parse_list(config['scan'])
            reserved.update(config['reserved'])
        except FileNotFoundError:
            return logging.error('Could not find scan file %s' % os.path.abspath(scanfile), 'main')
        except Exception as e:
            return logging.error(traceback.print_exc(), 'main')
    else:
        config = {}
        
    if len(scan_list) > 0:
        try:
            username, password = SSH.info_prompt()
        except:
            return logging.error(traceback.print_exc(), 'main')
        
    switchmap = {}
    for group in scan_list:
        switchmap.setdefault(group,{})
        for group_name in scan_list[group]:
            switchmap[group].setdefault(group_name,{})
            ips = scan_list[group][group_name]
            if group in current_switches and group_name in current_switches:
                switchmap[group][group_name].update(current_switches[group][group_name])
            for ip in ips:
                logging.info('Checking host: %s' % ip, 'map')
                print('Checking host: %s' % ip)
                if ip in reserved:
                    logging.info('%s is a reserved address.' % ip, 'map')
                    switchmap[group][group_name][ip] = reserved[ip]
                    continue
                try:
                    if ip in current_switches and 'Firmware' in current_switches[group][group_name][ip].keys():
                        switchmap[group][group_name][ip] = SwitchMap.map_host(SSH.connect(username, password, ip, current_switches[ip]['Firmware']))
                    else:
                        switchmap[group][group_name][ip] = SwitchMap.map_host(SSH.connect(username, password, ip))
                except Exception as e:
                    if str(e) != 'Offline':
                        logging.error(traceback.print_exc(), 'main')
                    switchmap[group][group_name][ip] = {'IP Address': ip, 'Make': 'NOLOGIN' if str(e) != 'Offline' else 'Offline'}

    if len(switchmap) > 0:
        mergelist = SwitchMap.savelist(switchmap, current_switches, jsonfile)
    else:
        mergelist = current_switches
    # Write list to CSV
    flat_list = []
    for sheet in mergelist:
        for subnet in sheet:
            for host in subnet:
                host.setdefault("Model","")
                flat_list.append(host)
    with open(csvfile, 'w') as f:
        header = ["IP Address","Hostname","Subnet Mask","Make","Model","Firmware","Serial","FIPS Mode","Upstream","Last Seen Online","Last Updated"]
        writer = csv.DictWriter(fieldnames=header)
        writer.writerows(flat_list)
    logging.info('Completed Successfully!')

main()
