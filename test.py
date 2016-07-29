"""
This test utilizes LdxCmd and Python swifttest.py module to compile a set of TDE projects into *.ini files for
further comparison. It was developed to perform the correctness of the API.
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


class Table():
    _rows = list()
    _separators = list()
    _column_cnt = 0
    _column_width = list()
    _margin_width = 2

    def __init__(self):
        self._rows = list()
        self._separators = list()
        self._column_cnt = 0
        self._column_width = list()
        self._margin_width = 1

    def add_sep(self, sep='-'):
        self._separators.append((len(self._rows), sep))

    def add_row(self, row=list(), align=Alignment.LEFT):
        data = dict({'data':row, 'options': {'align': align}})
        options = dict()
        self._rows.append(data)
        # recalculate the number of columns in table
        self._column_cnt = max([self._column_cnt, len(row)])
        # extend the _column_width list to the number of columns
        for i in range(0, self._column_cnt - len(self._column_width)):
            self._column_width.append(0)
        # update _column_width considering the length of elements in row
        for n in range(len(row)):
            self._column_width[n] = max([self._column_width[n], len(row[n])])

    def add_header(self, header):
        self.add_sep('=')
        self.add_row(header)
        self.add_sep('=')

    def extend(self, rows=list()):
        for row in rows:
            self.add_row(row)

    def get_row_str(self, row):
        row_str = ''
        align = row['options']['align']
        data = row['data']
        for n in range(self._column_cnt):
            column_width = self._column_width[n]
            space_len = column_width - len(data[n])
            indent_left = 0
            indent_right = 0
            if align == Alignment.LEFT:
                indent_right += space_len
            else:
                if align == Alignment.RIGHT:
                    indent_left += space_len
                else:
                    if align == Alignment.CENTER:
                        indent_left += space_len//2
                        indent_right += column_width - len(data[n]) - indent_left
            indent_left += self._margin_width
            indent_right += self._margin_width
            row_str += ' ' * indent_left + data[n] + ' ' * indent_right + '|'
        return row_str

    def output(self):
        if len(self._rows) > 1:
            for n in range(0, len(self._rows)):
                if len(self._separators) and self._separators[0][0] == n:
                    sep_str = self._separators[0][1]
                    sep_str *= (self._margin_width * 2 * (1 + self._column_cnt) + sum(self._column_width))
                    print(sep_str)
                    self._separators.pop(0)
                print(self.get_row_str(self._rows[n]))


def comapre_ini(ini_paths):
    configs = list()
    common_prefix_len = len(os.path.commonprefix(ini_paths))
    # iterate all ini files and make a list of (folder_name, ConfigParser) items
    for ini_path in ini_paths:
        folder_name = ini_path[common_prefix_len:].split(os.sep)[0]
        configs.append((folder_name, ConfigParser.RawConfigParser()))
        configs[-1][1].read(ini_path)

    # build a united structure of all sections in all configs
    conf_structure = dict()
    result_table = Table()
    header = list()
    header.append('')
    for folder_name, conf in configs:
        # compose the header of the result table
        header.append(folder_name)
        for section in conf.sections():
            if not conf_structure.has_key(section):
                conf_structure[section] = set()
            conf_structure[section] |= set(conf.options(section))

    result_table.add_header(header)

    for section in conf_structure:
        section_values = list()
        option_values = list()
        section_values.append(section)
        for folder_name, conf in configs:
            if conf.has_section(section):
                section_values.append('+')
            else:
                section_values.append('-')
        for option in conf_structure[section]:
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
            if len(set(values)) > 2:
                option_values.append(values)
        # add to output: name of the section and its state (present/absent) for each conf
        if len(set(section_values)) > 2 or len(option_values):
            result_table.add_row(section_values)
            if len(option_values):
                result_table.extend(option_values)
    result_table.output()


                # print()
    # sys.exit(0)


def check(obj_dirs):
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
            ini = set([i for i in os.listdir(port_dir) if (re.match('[\w\.]+\.ini$', i))])
            if not len(common_ini):
                common_ini = ini
            else:
                common_ini = common_ini & ini

        if not len(common_ini):
            print('Check: no common ini files', file=sys.stderr)
        else:
            print('\nComparing port: ', port)
            for ini in common_ini:
                print ('\n' + ini)
                ini_paths = set()
                for obj_dir in obj_dirs:
                    ini_dir = os.path.join(obj_dir, port, ini)
                    ini_paths.add(ini_dir)
                comapre_ini(ini_paths)


#
# Main
#
def main():
    # build a set of test paths from the command line argument pointing to the root folder
    parser = argparse.ArgumentParser()
    parser.add_argument('test_path', help='path to tests', type=str)
    args = parser.parse_args()
    path_list = dig_tests(args.test_path)
    LDXCMD_BIN = find_ldxcmd()

    # Convert TDE projects to AutomationConfig
    for project_dir in path_list:
        project_name = os.path.split(project_dir)[-1]
        print(project_name)

        # convert
        cur_dir = os.path.abspath(os.path.curdir)
        config_dir = os.path.join(cur_dir, 'AutomationConfig', project_name)
        convert(LDXCMD_BIN, project_dir, config_dir)

        # obj_dirs = '/Volumes/public/exchange/dabakumov/temp/api/py/obj/HTTP piplining auth and redirect', '/Volumes/public/exchange/dabakumov/temp/api/tde/obj/HTTP piplining auth and redirect'#, '/Volumes/public/exchange/dabakumov/temp/api/py/obj/HTTP pipelinig Apache'
                   # '/Volumes/public/exchange/dabakumov/temp/api/py/obj/HTTP GET 10 files pipelined'

        # compile to *.ini files
        obj_dirs = compile(LDXCMD_BIN, config_dir, cur_dir)
        for obj_dir in obj_dirs:
            print (obj_dir)
        check(obj_dirs)

        print()

if __name__ == '__main__':
    main()
