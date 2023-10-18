# $language = "python3"
# $interface = "1.0"

import pandas as pd
import traceback, logging
import json, os
log = logging.Logger(__name__)

# List of background cell colors for banded rows sorted by CN/CDN
# Formatted: [<header bg>, <even rows bg>, <odd rows bg>]
BG = [
  ['#64B5F6','#BBDEFB','#E3F2FD'],
  ['#81C784','#C8E6C9','#E8F5E9'],
  ['#FFB300','#FFE082','#FFF8E1'],
  ['#7986CB','#C5CAE9','#E8EAF6'],
  ['#E57373','#FFCDD2','#FFEBEE'],
  ['#BA68C8','#E1BEE7','#F3E5F5'],
  ['#4f81bd','#b8cce4','#dce6f1'],
  ['#c0504d','#e6b8b7','#f2dcdb'],
  ['#9bbb59','#d8e4bc','#ebf1de'],
  ['#8064a2','#ccc0da','#e4dfec'],
  ['#4bacc6','#b7dee8','#daeef3'],
  ['#f79646','#fcd5b4','#fde9d9'],
]

'''
  Style function applied to each row to determine banded colors of each cell
'''
def mark_offline(row, sheet):
  row_ip = row['IP Address']
  if row['Make'] == 'Offline':
    log.debug(f'%s: Using color #D3D3D3 for {row_ip}', 'mark_offline')
    return ['background-color: #D3D3D3'] * len(row)
  # pull color based on sheet number
  colors = BG[sheet % len(BG)]
  if row['Make'] == 'Reserved':
    return ['font-weight: bold ; background-color: %s ; color: #ffffff' % colors[0]] * len(row)
  color = colors[row.name%2 + 1]
  log.debug(f'%s: Formatting background for {row_ip} as {color}', 'mark_offline')
  return [f'background-color: {color}'] * len(row)

'''
  Returns a sorted map of switches including an 'ALL' group
'''
def sort_switches(switches):
  sorted = {}
  for sheet in switches:
    sorted.setdefault('ALL',{}).update(switches[sheet])
    sorted.setdefault(sheet, {}).update(switches[sheet])
  return sorted

def same_stack(old, current):
  new = current.copy()
  for serial in old:
      if serial in new:
        new.remove(serial)
      else:
        return False
  return True

def ip_to_decimal(ip):
	log.debug(f'%s: Converting ip {ip} to decimal value', 'ip_to_deciaml')
	if ip == 'F':
		return 0
	octets = ip.split('.')
	decimal = 0
	for i in range(len(octets)):
		decimal += int(octets[i]) * pow(2, 8*(3-i))
	return decimal

def dfsort(series):
  return series.apply(lambda x: ip_to_decimal(x))

'''
  Updates each individual sheet within an excel file with all values contained within switches
'''
def update_sheet(switches,dataframe=None):
  columns = ["Hostname","IP Address","Subnet Mask","Make","Model","Firmware","Serial","FIPS Mode","Upstream","Last Seen Online","Last Updated"]
  if dataframe is None:
    log.info(f'%s: Creating new Dataframe for group', 'update_sheet')
    dataframe = pd.DataFrame(data=switches,columns=columns)
  header = dataframe.columns.tolist()
  # If sheet has an invalid format, cancel update
  if not 'IP Address' in header:
    log.warn(f'%s: Skipped sheet, missing IP Address index', 'update_sheet')
    return dataframe
  insert_index = 0
  for subnet_group in switches:
    for switch_ip in switches[subnet_group]:
      skip = False
      if not 'IP Address' in switches[subnet_group][switch_ip].keys():
        switches[subnet_group][switch_ip]['IP Address'] = switch_ip
      for key in switches[subnet_group][switch_ip]:
        if not key in columns:
          log.debug(f'%s: Device {switch_ip} has excess key {key}', 'update_sheet')
          skip = True
      if skip:
        log.info(f'%s: Skipping switch {switch_ip}', 'update_sheet')
        continue
      log.debug(f'%s: Updating info for switch {switch_ip}', 'update_sheet')
      switch = switches[subnet_group][switch_ip]
      for column in columns:
        switch.setdefault(column, '')
        if isinstance(switch[column], list):
            switch[column] = ','.join(switch[column])
      # row contains the list of indexes with matching 'IP Address'
      row = dataframe.index[dataframe['IP Address'] == switch_ip]
      # add new row to list if IP does not exist
      try:
        if len(row) == 0:
          switch_frame = pd.DataFrame(data=switch, index=[0], columns=columns)
          dataframe = pd.concat([switch_frame, dataframe], axis=0, ignore_index=True)
          row = dataframe.index[dataframe['IP Address'] == switch_ip]
          insert_index+=1
          log.info(f'%s: Appended new row for {switch_ip}', 'update_sheet')
        if len(row) > 1:
          log.error(f'%s: MULTIPLE IPs FOUND: {switch_ip}', 'update_sheet')
          continue
        index = row[0] 
        # dataframe.iloc[index][key] returns the actual cell value at the matched index
        # update all columns with new info
        for col in switch.keys():
          try:
            dataframe.loc[index, col] = switch[col]
          except:
            log.debug(f'%s: No value for {col} found in sheet', 'update_sheet')
        insert_index += 1
      except:
        log.error(f'%s: Unable to add row for {switch_ip}', 'udpate_sheet')
        log.error(f'%s: {traceback.print_exc()}', 'update_sheet')
        log.debug(f'%s: Bad row value: {json.dumps(switch, indent=2)}', 'update_sheet')
  return dataframe.sort_values(by='IP Address',key=dfsort).reindex(columns=columns)
  
'''
  Reads an existing excel file as a switch list (or creates one if the given file doesn't exist)
  and updates with current values in @param(switches)

  Saves data in a temporary file 'tempfile.xlsx' during runtime to prevent corruption of main file.
'''
def update_file(infile, switches):
  log.info(f'%s: Reading file {infile}', 'update_file')
  if os.path.exists(infile):
    file_handler = pd.ExcelFile
  else:
    file_handler = pd.ExcelWriter
  with file_handler(infile) as xl_file:
      tempfile = 'tempfile.xlsx'
      sorted = sort_switches(switches)
      with pd.ExcelWriter(tempfile, engine='xlsxwriter') as writer:
        sheet_count = 0
        for sheet in sorted:
          log.info(f'%s: Parsing sheet {sheet}', 'update_file')
          if isinstance(xl_file, pd.ExcelWriter) or not sheet in xl_file.sheet_names:
            df = update_sheet(sorted[sheet])
          else:
            df = update_sheet(sorted[sheet],xl_file.parse(sheet))
          try:
            df.style.set_properties(**{'background-color': BG[sheet_count % len(BG)][0]}).to_excel(writer,sheet_name=sheet,index=False)
            df.style.apply(mark_offline, sheet=sheet_count, axis=1).to_excel(writer,sheet_name=sheet,index=False)
            worksheet = writer.sheets[sheet]
            # Get the dimensions of the dataframe.
            (max_row, max_col) = df.shape
            # Set the autofilter.
            worksheet.autofilter(0, 0, max_row, max_col - 1)
          except:
            log.info(f'%s: Writing sheet {sheet} as is', 'update_file')
            df.to_excel(writer,sheet_name=sheet,index=False)
          sheet_count+= 1
        log.debug(f'%s: Writing to file {infile}', 'update_file')
        writer.close()
  os.remove(infile)
  os.rename(tempfile,infile)