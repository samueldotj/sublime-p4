"""
Latest version can be obtained by https://github.com/samueldotj/sublime-p4
Based on perforce plugin created by Eric Martel.
"""

import sublime
import sublime_plugin

import os
import stat
import subprocess
import tempfile
import threading

def _warn_user(message):
    """ Display warning message if warnings are enabled else just log it.
    """
    msg = "P4 [warning]: {0}".format(message)
    p4_settings = sublime.load_settings('P4.sublime-settings')
    if p4_settings.get('p4_warnings_enabled'):
        sublime.status_message(msg)
    print(msg)

def _show_message(edit, msg):
    """ Shows given message.
    """
    win = sublime.active_window()
    v = win.new_file()
    v.set_syntax_file('Packages/Diff/Diff.tmLanguage')
    v.insert(edit, 0, msg)
    v.set_scratch(True)

def _is_file_writeable(file_path):
    """ Returns True if the given file is writable.
    """
    if file_path is None:
        return False

    # if it doesn't exist, it's "writable"
    if not os.path.isfile(file_path):
        return True

    filestats = os.stat(file_path)[0]
    if filestats & stat.S_IWRITE:
        return True
    return False

def _read_p4_config_values(config_file_path):
    """ Read perforce specific environmental values from a config file :(
        Config file format is ENV_VAR_NAME=value
        For example:
        P4PORT=xyz.com:3837
        P4CLIENT=myclient
    """
    result = {}
    with open(config_file_path) as config_file:
        for line in config_file:
            var, value = line.split('=')
            result[var.strip()] = value.strip()
    return result

def _get_p4_config(path):
    """ Search p4 config file(which has the environmental values).
        Basicaly this function looks for a file ".p4config" in current directory,
        parent directory, parent's parent directory ... until root directory.
    """
    while path and path != '' and path != '/':
        config_file = os.path.join(path, '.p4config')
        if os.path.isfile(config_file):
            return _read_p4_config_values(config_file)
        path = os.path.dirname(path)

    return None

def _run_p4_command(p4_cmd):
    """ Runs the given p4 command and returns result and error.
    """
    file_path = sublime.active_window().active_view().file_name()
    folder = os.path.dirname(file_path)

    p4_config = _get_p4_config(file_path)
    env = os.environ.copy()
    env.update(p4_config)
    process = subprocess.Popen(p4_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               cwd=folder, shell=True, env=env)
    result, err = process.communicate()
    if result:
        result = result.decode("utf-8").strip()
    if err:
        err = err.decode("utf-8").strip()
        if err == '':
            err = None
        else:
            _warn_user(err)
    if err:
        print("{0} failed: {1}".format(p4_cmd, err))

    return result, err


def _get_user_from_client_spec():
    """ Returns UserName from p4 client spec.
    """
    result, err = _run_p4_command('p4 -F %userName% -z tag info')
    if err or result == '':
        return None

    return result

def _get_client_root_directory():
    """ Returns p4 client root directory path.
    """
    result, err = _run_p4_command('p4 -F %clientRoot% -z tag info')
    if err or result == '':
        return None
    return result

def _is_file_in_depot(file_path):
    """ Returns True if the file is in the depot
    """
    client_root = _get_client_root_directory()
    return file_path.startswith(client_root)


class P4LoginCommand(sublime_plugin.WindowCommand):
    """ Login command handler
    """
    def run(self):
        self.window.show_input_panel("Enter P4 Password", "", self.on_done, None, None)

    def on_done(self, password):
        try:
            _run_p4_command("p4 logout")
            #unset var
            _run_p4_command("p4 set P4PASSWD={0}".format(password))
        except ValueError:
            pass


class P4LogoutCommand(sublime_plugin.WindowCommand):
    """ Logout command handler
    """
    def run(self):
        try:
            _run_p4_command("p4 set P4PASSWD=")
        except ValueError:
            pass


def _p4_open(file_path):
    """ open/edit the given file
    """
    if file_path is None:
        return

    settings = sublime.load_settings('P4.sublime-settings')

    # check if this part of the plugin is enabled
    if not settings.get('p4_auto_open'):
        return

    if _is_file_writeable(file_path):
        print("File is already writable.")

    if not _is_file_in_depot(file_path):
        print("File is not under the client root.")

    # check out the file
    _run_p4_command('p4 edit "{path}"'.format(path=file_path))


class P4AutoOpen(sublime_plugin.EventListener):
    """ Automatically open file when modified or before saving.
    """
    def on_pre_save(self, view):
        if not view.is_dirty():
            return

        _p4_open(view.file_name())


class P4OpenCommand(sublime_plugin.TextCommand):
    """ p4 open - Command handler
    """
    def run(self, edit):
        _p4_open(self.view.file_name())


class P4AutoAdd(sublime_plugin.EventListener):
    """ Automatically add files on after save.
    """
    def on_post_save(self, view):
        file_path = view.file_name()
        p4_settings = sublime.load_settings('P4.sublime-settings')

        # check if this part of the plugin is enabled
        if not p4_settings.get('p4_auto_add'):
            return

        if not _is_file_in_depot(file_path):
            return
        cmd = 'p4 add "{file}"'.format(file=file_path)
        _run_p4_command(cmd)


class P4AddCommand(sublime_plugin.TextCommand):
    """ p4 add - command handler
    """
    def run(self, edit):
        filename = self.view.file_name()
        if _is_file_in_depot(filename):
            cmd = 'p4 add "{file}"'.format(file=filename)
            _run_p4_command(cmd)
        else:
            _warn_user("File is not under the client root.")


class P4DeleteCommand(sublime_plugin.WindowCommand):
    """ p4 delete - command handler
    """
    def run(self):
        filename = self.window.active_view().file_name()
        if _is_file_in_depot(filename):
            cmd = 'p4 delete "{file}"'.format(filename)
            result, err = _run_p4_command(cmd)
            if not err: # the file was properly deleted on perforce, ask Sublime Text to close the view
                self.window.run_command('close')
        else:
            _warn_user("File is not under the client root.")


class P4RevertCommand(sublime_plugin.TextCommand):
    """ p4 revert - command handler
    """
    def run_(self, edit_token, args): # revert cannot be called when an Edit object exists, manually handle the run routine
        filepath = self.view.file_name()
        if _is_file_in_depot(filepath):
            cmd = 'p4 revert "{file}"'.format(filepath)
            result, err = _run_p4_command(cmd)
            if not error: # the file was properly reverted, ask Sublime Text to refresh the view
                self.view.run_command('revert')
        else:
            _warn_user("File is not under the client root.")


class P4DiffCommand(sublime_plugin.TextCommand):
    """ p4 diff <file>- command handler
    """
    def run(self, edit):
        filepath = self.view.file_name()
        if not _is_file_in_depot(filepath):
            _warn_user("File is not under the client root.")
            return

        result, err = _run_p4_command('p4 diff -dU "{file}"'.format(file=filepath))
        if result:
            _show_message(edit, result)


class P4DiffAllCommand(sublime_plugin.TextCommand):
    """ p4 diff - command handler
    """
    def run(self, edit):
        filepath = self.view.file_name()
        if not _is_file_in_depot(filepath):
            _warn_user("File is not under the client root.")
            return

        result, err = _run_p4_command('p4 diff -dU')
        if result:
            _show_message(edit, result)


class P4OpenedCommand(sublime_plugin.TextCommand):
    """ p4 opened - command handler
    """
    def run(self, edit):
        result, err = _run_p4_command('p4 opened')
        if result:
            _show_message(edit, result)
