#! /usr/bin/python

"""
This test checks the way TDE and API compile Ldx projects into INI files.
It utilizes LdxCmd and Python swifttest.py module to compile projects into *.ini files.
A path to Ldx projects should be given as the only input parameter to the script.
Every subfolder in the input folder will be recursively checked for containing an Ldx project.
Then every project found will be converted to AutomationConfig which in its turn will be
compiled to ini using LdxCmd and Python API. The result of each of the two compilations will
be placed into the corresponding folder (tde or py) for further comparison.
The comparison is being done using the Python's ConfigParser module.
For each ini file a table is generated listing all values unequal between py and tde.
These unequal values fall into 3 categories:
  -- default: value may not be present in the ini, in which case it will be dafaulted by
              the backend.
  -- ignore:  technically, this value can not be equal (e.g., timestamp or GUID) but this
              has no impact on test execution.
  -- unequal: all the rest of unequal values are marked in red and should be evaluated.
              These may reveal possible mismatch between TDE and API code.
The ./exceptions folder contains files with their ignored or default values.
"""

from __future__ import print_function
import swifttest
import argparse
import os
import sys
import re
import subprocess
import shutil
import ConfigParser


if sys.platform.startswith("win"):
    import _winreg


#
# Constants
#
SWIFTTEST_PROJECT_FILE_EXT = ".swift_test"
WINDOWS_GUID_RX = "\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}$"
SWIFTTEST_PROJECT_FILE_RX = '.*\.swift_test$'
PORT_RX = '(Client|Server)_Port_\d+'


# alignment types for table output
class Alignment:
    CENTER = 0
    LEFT = 1
    RIGHT = 2


def copyDirectory(src, dest):
    try:
        shutil.copytree(src, dest)
    # Directories are the same
    except shutil.Error as e:
        print('Directory not copied. Error: %s' % e)
    # Any error saying that the directory doesn't exist
    except OSError as e:
        print('Directory not copied. Error: %s' % e)


def is_project(path):
    for s in os.listdir(path):
        if not s.startswith('.'):
            subitem = os.path.join(path, s)
            if os.path.isfile(subitem):
                ext = os.path.splitext(s)
                if ext[1] == SWIFTTEST_PROJECT_FILE_EXT:
                    return True
    return False


def dig_tests(path, depth=256):
    """
    Look through the directory tree starting from 'path' to the given 'depth' and return a list of
    full paths to test projects found. [depth == 1: no search in subfolders; default: search to the depth of 256]
    """
    if depth > 256:
        depth = 256
    elif depth < 0:
        depth = 0
    result = set()
    if is_project(path):
        result.add(path)
    else:
        if depth > 0:
            depth -= 1
            for si in os.listdir(path):
                sub_item = os.path.join(path, si)
                if os.path.isdir(sub_item):
                    result |= (dig_tests(sub_item, depth))
    return result


def find_ldxcmd():
    if sys.platform.startswith("win"):
        # Read from SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall
        # Setting security access mode. KEY_WOW64_64KEY is used for 64-bit TDE
        sam = _winreg.KEY_READ | _winreg.KEY_WOW64_64KEY
        reg_key = _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0,
                                  sam)
        latest_version = ""
        latest_build = 0
        path_to_latest_build = ""
        # iterate through all subkeys of \Uninstall
        for i in xrange(0, _winreg.QueryInfoKey(reg_key)[0]):
            try:
                subkey = _winreg.EnumKey(reg_key, i)
                if re.match(WINDOWS_GUID_RX, subkey):
                    tde_key = _winreg.OpenKey(reg_key, subkey)
                    display_name = str(_winreg.QueryValueEx(tde_key, "DisplayName")[0])
                    if display_name.startswith("Load DynamiX TDE"):
                        display_version = str(_winreg.QueryValueEx(tde_key, "DisplayVersion")[0])
                        match = re.match("(\d+).(\d+).(\d+)", display_version)
                        if match:
                            tde_build = int(match.group(3))
                            if tde_build > latest_build:
                                path_to_build = str(_winreg.QueryValueEx(tde_key, "InstallLocation")[0])
                                path_to_build = os.path.join(path_to_build, "LdxCmd.exe")
                                if os.path.exists(path_to_build):
                                    latest_version = display_version
                                    latest_build = tde_build
                                    path_to_latest_build = path_to_build
            except EnvironmentError:
                break
        if latest_build > 0:
            print ("The latest LdxCmd version found: " + latest_version)
            return path_to_latest_build
        else:
            raise Exception('LdxCmd.exe not found.')
    else:
        if not os.path.exists("/opt/swifttest/resources/dotnet/LdxCmd"):
            raise Exception('LdxCmd executable not found: /opt/swifttest/resources/dotnet/LdxCmd')
        return "/opt/swifttest/resources/dotnet/LdxCmd"


def get_files(directory, pattern):
    """Return a list of file paths that match the given regex pattern inside the directory."""
    return [os.path.join(directory, f) for f in os.listdir(directory) if re.match(pattern, f) and not f.startswith('.')]


def convert(LDXCMD_BIN, project_dir, config_dir):
    """Convert TDE project to AutomationConfig."""
    project_files = get_files(project_dir, SWIFTTEST_PROJECT_FILE_RX)
    if len(project_files) > 1:
        raise Exception('More than one .swift_test file found in dir: %s' % project_dir)
    if len(project_files) == 0:
        raise Exception('No .swift_test file found in dir: %s' % project_dir)
    project_file = project_files[0]
    # find the path to LdxCmd
    print ('Converting project to AutomationConfig.')
    p = subprocess.Popen([LDXCMD_BIN,
                          '--generate', '--project:' + project_file,
                          '--upgrade',
                          '--Force',
                          '--out:' + config_dir], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = p.communicate()
    if p.returncode:
        print(output)
        raise Exception('An error occured during conversion.')


def generate(config_dir, generate_dir):
    project_name = os.path.split(config_dir)[-1]
    p = subprocess.Popen(['/opt/swifttest/bin/swiftgenerator',
                          '--name=' + project_name,
                          '--inpath=\'' + os.path.join(config_dir, 'AutomationConfig.xml\''),
                          '--outpath=\'' + os.path.join(generate_dir, 'py', project_name) + '\'',
                          '--python'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = p.communicate()
    if p.returncode:
        print(output)
        raise Exception('An error occured during generation.')


def compile (LDXCMD_BIN, config_dir, compile_dir):
    # compile using python swifttest API
    project_name = os.path.split(config_dir)[-1]
    obj_dir_api = os.path.join(compile_dir, 'py', 'obj', project_name)
    if not os.path.exists(obj_dir_api):
        os.makedirs(obj_dir_api)
    config_xml = os.path.join(config_dir, 'AutomationConfig.xml')
    project = swifttest.Project(project_name, config_xml)
    logger = swifttest.Logger()
    if not project.compile(obj_dir_api, True, logger):
        for msg in logger.each_error():
            if msg:
                print('An error occurred during compilation: ' + msg.text, file=sys.stderr)

    # compile using LdxCmd
    obj_dir_tde = os.path.join(compile_dir, 'tde', 'obj', project_name)
    p = subprocess.Popen([LDXCMD_BIN, '--compile', '--config:' + config_xml],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = p.communicate()
    if p.returncode:
        print(output)
        raise Exception('An error occurred during compilation.')
    else:
        if os.path.exists(obj_dir_tde):
            shutil.rmtree(obj_dir_tde)
        copyDirectory(os.path.join(config_dir, 'Automation', 'obj'), obj_dir_tde)
        # rename port folders using underscores instead of spaces
        for f in os.listdir(obj_dir_tde):
            if os.path.isdir(os.path.join(obj_dir_tde, f)) and re.match('(Client|Server)\sPort\s\d+', f):
                new_f = f.replace(' ', '_')
                os.rename(os.path.join(obj_dir_tde, f), os.path.join(obj_dir_tde, new_f))
    return obj_dir_api, obj_dir_tde


Colors = dict({
    'Red': '\033[91m',
    'Green': '\033[92m',
    'Blue': '\033[94m',
    'Cyan': '\033[96m',
    'White': '\033[97m',
    'Yellow': '\033[93m',
    'Magenta': '\033[95m',
    'Grey': '\033[90m',
    'Black': '\033[90m',
    'Default': '\033[99m',
    'ENDC': '\033[0m',
    'BOLD': '\033[1m',
    'UNDERLINE': '\033[4m'
})


class Row:
    data = list()
    align = Alignment.LEFT
    font = 'Default'

    def __init__(self, data=list(), align=Alignment.LEFT, font='Default'):
        self.data = data
        self.align = align
        self.font = font

    def column_cnt(self):
        return len(self.data)

    def add_col(self, text=''):
        self.data.append(text)

    def extend_to(self, col_num=1):
        for i in range(col_num - self.column_cnt()):
            self.add_col()


class Table:
    _rows = list()
    _separators = list()
    _column_cnt = 0
    _column_width = list()
    _margin_width = 2
    _caption = ''
    _totals = list()

    def __init__(self, caption=''):
        self._rows = list()
        self._separators = list()
        self._column_cnt = 0
        self._column_width = list()
        self._margin_width = 1
        self._caption = caption
        self._totals = list()

    def add_sep(self, sep='-'):
        self._separators.append((len(self._rows), sep))

    def add_row(self, row):
        row.extend_to(self._column_cnt)
        self._rows.append(row)
        # recalculate the number of columns in table
        self._column_cnt = max([self._column_cnt, row.column_cnt()])
        # extend the _column_width list to the number of columns
        for i in range(0, self._column_cnt - len(self._column_width)):
            self._column_width.append(0)
        # update _column_width considering the length of elements in row
        for n in range(row.column_cnt()):
            self._column_width[n] = max([self._column_width[n], len(str(row.data[n]))])

    def add_header(self, header):
        self.add_sep('=')
        self.add_row(Row(header, align=Alignment.CENTER))
        self.add_sep('=')

    def add_total(self, name, value):
        data = [name, str(value)]
        for i in range(self._column_cnt-2):
            data.insert(1, '')
        self._totals.append(Row(data, align=Alignment.RIGHT, font='BOLD'))

    def get_row_str(self, row, total=False):
        align = row.align
        font = Colors.get(row.font)
        data = row.data
        row_str = font
        for n in range(self._column_cnt):
            column_width = self._column_width[n]
            space_len = column_width - len(str(data[n]))
            indent_left = 0
            indent_right = 0
            if align == Alignment.LEFT or (n == 0 and not total):
                indent_right += space_len
            else:
                if align == Alignment.RIGHT:
                    indent_left += space_len
                else:
                    if align == Alignment.CENTER:
                        indent_left += space_len//2
                        indent_right += column_width - len(str(data[n])) - indent_left
            indent_left += self._margin_width
            indent_right += self._margin_width
            row_str += ' ' * indent_left + str(data[n]) + ' ' * indent_right + '|'
        row_str += Colors.get('ENDC')
        return row_str

    def get_width(self):
        result = self._margin_width * 2 * (1 + self._column_cnt) + sum(self._column_width) + 1
        return result

    def output(self):
        print('_' * max(len(self._caption), self.get_width()))
        print(self._caption)
        if len(self._rows) > 1:
            for n in range(0, len(self._rows)+1):
                # if a separator has been inserted in the position of n
                if len(self._separators) and self._separators[0][0] == n:
                    # print a separator line
                    sep_str = self._separators[0][1]
                    sep_str *= (self.get_width())
                    print(sep_str)
                    self._separators.pop(0)
                if n < len(self._rows):
                    print(self.get_row_str(self._rows[n]))
            for t in self._totals:
                print(self.get_row_str(t, True))
        else:
            print('< nothing to output >')


def compare_ini(ini_dirs, ini_name):
    # list of configuration INI readers
    configs = list()
    common_prefix_len = len(os.path.commonprefix(ini_dirs))
    # iterate all ini files and make a list of (folder_name, ConfigParser) items
    for ini_dir in ini_dirs:
        # extract the first unique item of the path to use as an identifier of ini files set
        folder_name = ini_dir[common_prefix_len:].split(os.sep)[0]
        configs.append((folder_name, ConfigParser.RawConfigParser()))
        configs[-1][1].read(os.path.join(ini_dir, ini_name))

    # initialize exceptions from the corresponding exceptions *.ini
    exceptions = ConfigParser.RawConfigParser()
    file_name, file_ext = os.path.splitext(ini_name)
    exception_ini = file_name.strip('1234567890') + file_ext
    exception_ini = os.path.join('exceptions', exception_ini)
    if os.path.exists(exception_ini):
        exceptions.read(exception_ini)

    # build a united structure of all sections in all configs
    conf_structure = dict()
    result_table = Table(ini_name)
    header = list()
    header.append('')
    for folder_name, conf in configs:
        # compose the header of the result table
        header.append(folder_name)
        for section in conf.sections():
            if not conf_structure.has_key(section):
                conf_structure[section] = set()
            conf_structure[section] |= set(conf.options(section))
    header.append('status')
    result_table.add_header(header)
    # initializing statistic counters
    ignored_cnt = 0
    default_cnt = 0
    unequal_cnt = 0
    for section in conf_structure:
        section_exc = section.strip('1234567890')
        section_values = list()
        option_values = list()
        section_values.append(section)
        for folder_name, conf in configs:
            if conf.has_section(section):
                section_values.append('+')
            else:
                section_values.append('-')
        for option in conf_structure[section]:
            option_exc = option.strip('1234567890')
            value_exc = 'unequal'
            # if current option is marked 'ignore' in exceptions list - don't check it
            if exceptions.has_section(section_exc):
                if exceptions.has_option(section_exc, option_exc):
                    value_exc = exceptions.get(section_exc, option_exc)
            values = list()
            values.append('  ' + str(option))
            for folder_name, conf in configs:
                if conf.has_section(section):
                    if conf.has_option(section, option):
                        values.append(conf.get(section, option))
                    else:
                        values.append('-')
                else:
                    values.append('-')
            # if at least 2 different values are found - add a row to the table
            if len(set(values)) > 2:
                values.append(value_exc)
                option_values.append(values)
            # else:
            #     equal_cnt += 1
        # add to output: name of the section and its state (present/absent) for each conf
        if len(set(section_values)) > 2 or len(option_values):
            result_table.add_row(Row(section_values, align=Alignment.CENTER))
            for ov in option_values:
                value_exc = ov[-1]
                color = 'Default'
                if value_exc == 'unequal':
                    color = 'Red'
                    unequal_cnt += 1
                else:
                    if value_exc == 'ignore':
                        color = 'Grey'
                        ignored_cnt += 1
                    else:
                        if value_exc == 'default':
                            color = 'Blue'
                            default_cnt += 1
                result_table.add_row(Row(ov, font=color))
    result_table.add_sep()
    if ignored_cnt or default_cnt or unequal_cnt:
        result_table.add_total('Ignored:', ignored_cnt)
        result_table.add_total('Default:', default_cnt)
        result_table.add_total('Unequal:', unequal_cnt)
    result_table.output()
    return bool(unequal_cnt)


def check(obj_dirs):
    result = list()
    # build a list of port folders
    common_ports = set()
    for obj_dir in obj_dirs:
        ports = set()
        for port in next(os.walk(obj_dir))[1]:
            if re.match(PORT_RX, port):
                ports.add(port)
        if not len(common_ports):
            common_ports = ports
        else:
            common_ports = common_ports & ports

    # find common and odd port folders
    if not len(common_ports):
        print('No common ports in ', obj_dirs, file=sys.stderr)

    # iterate port folders
    for port in common_ports:
        common_ini = set()
        for obj_dir in obj_dirs:
            port_dir = os.path.join(obj_dir, port)

            # find common ini files
            ini_name = set([i for i in os.listdir(port_dir) if (re.match('[\w\.]+\.ini$', i))])
            if not len(common_ini):
                common_ini = ini_name
            else:
                common_ini = common_ini & ini_name

        if not len(common_ini):
            print('Check: no common ini files', file=sys.stderr)
        else:
            print('\nComparing port: ', port)
            for ini_name in common_ini:
                print()
                ini_dirs = set()
                for obj_dir in obj_dirs:
                    ini_dir = os.path.join(obj_dir, port)
                    ini_dirs.add(ini_dir)
                if compare_ini(ini_dirs, ini_name):
                    result.append(ini_name)
    return len(result)


#
# Main
#
def main():
    # build a set of test paths from the command line argument pointing to the root folder
    parser = argparse.ArgumentParser()
    parser.add_argument('test_path', help='path to folder containing TDE projects', type=str)
    args = parser.parse_args()
    path_list = dig_tests(args.test_path)
    LDXCMD_BIN = find_ldxcmd()
    result_table = Table('Total results')
    result_table.add_header(['Project', 'Files failed'])

    projects_failed = 0
    for project_dir in path_list:
        project_name = os.path.split(project_dir)[-1]
        print(project_name)

        # Convert TDE projects to AutomationConfig
        cur_dir = os.path.abspath(os.path.curdir)
        config_dir = os.path.join(cur_dir, 'AutomationConfig', project_name)
        convert(LDXCMD_BIN, project_dir, config_dir)

        # obj_dirs = '/Volumes/public/exchange/dabakumov/temp/api/py/obj/HTTP piplining auth and redirect', '/Volumes/public/exchange/dabakumov/temp/api/tde/obj/HTTP piplining auth and redirect'#, '/Volumes/public/exchange/dabakumov/temp/api/py/obj/HTTP pipelinig Apache'
                   # '/Volumes/public/exchange/dabakumov/temp/api/py/obj/HTTP GET 10 files pipelined'

        # compile to *.ini files
        obj_dirs = compile(LDXCMD_BIN, config_dir, cur_dir)
        for obj_dir in obj_dirs:
            print (obj_dir)
        files_failed = check(obj_dirs)

        result_table.add_row(Row([project_name, files_failed], align=Alignment.RIGHT))
        projects_failed += int(bool(files_failed))
        print()
    result_table.add_sep()
    result_table.add_total('Projects failed:', projects_failed)
    result_table.output()
    sys.exit(projects_failed)

if __name__ == '__main__':
    main()
