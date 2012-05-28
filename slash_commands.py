#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


class ExecutionError(Exception):
    pass

class PermissionError(Exception): #(admin, participant, observer)
    pass

class ArgFormatError(Exception):
    pass


class SlashCommand(object):
    def __init__(self, command_name, text_arg_format, text_description, validate_sender, validate_args, action):
        self._command_name = command_name
        self._text_arg_format = text_arg_format
        self._text_description = text_description
        self.validate_sender = validate_sender
        self.validate_args = validate_args  # should return the args as a list if they are valid. an empty arg list shouldn't raise an error!
        self._action = action

    def execute(self, sender, arg_string):
        if not self.validate_sender(sender):
            raise PermissionError
        # pass the sender to validate_args in case the args depend on it or in case it *should* be an arg
        # also note that .split(' ') returns arrays with the empty string as an element, so filter those out
        args = self.validate_args(sender, filter(lambda arg: arg != '', arg_string.split(' ')))
        if args is False:
            raise ArgFormatError
        return self._action(*args)

    def __getattr__(self, name):
        if name == 'name':
            return self._command_name
        elif name == 'arg_format':
            return self._text_arg_format
        elif name == 'description':
            return self._text_description
            
class SlashCommandRegistry(object):
    def __init__(self):
        self.slash_commands = {}

    def is_command(self, message):
        message = message.lstrip()
        return message.startswith('/') and len(message.lstrip('/')) > 0

    def handle_command(self, sender, message):
        message = message.strip().lstrip('/')
        try:
            command_name, _, args = message.partition(' ')
        except ValueError:
            return 'The command was not formatted properly. Please separate the command from the arguments with a single space.'
        if command_name in self.slash_commands:
            slash_command = self.slash_commands[command_name]
            try: 
                result_message = slash_command.execute(sender, args)
                return result_message or 'Your /%s command was successful.' % slash_command.name
            except ExecutionError, error:
                return 'Sorry, but there was an error executing this command:\n\t%s' % error
            except PermissionError:
                return 'Sorry, but you do not have permission to use this command.'
            except ArgFormatError:
                return 'The arguments were not formatted properly. Please use:\n\t/%s %s' % \
                    (slash_command.name, slash_command.arg_format)
        elif command_name == 'help':
            command_string = ''
            for slash_command in self.slash_commands.values():
                if slash_command.validate_sender(sender):
                    command_string += '\t/%s %s: %s\n' % (slash_command.name, slash_command.arg_format, slash_command.description)
            if command_string == '':
                return 'You do not have permission to execute any commands with this bot.'
            else:
                return 'The available commands are:\n' + command_string
                
        else:
            return 'Sorry, %s is not a registered command. Type /help to see a full list.' % command_name
   
    def add(self, slash_command):
        if slash_command.name in self.slash_commands:
            logging.error('%s is already a registered command.' % slash_command.name)
        elif slash_command.name == 'help':
            logging.error('The /help command is built in and can not be added.' % slash_command.name)
        else:
            self.slash_commands[slash_command.name] = slash_command

    def remove(self, command_name):
        if command_name in self.slash_commands:
            del self.slash_commands[command_name]
        elif command_name == 'help':
            logging.error('The /help command is built in and can not be removed.' % command_name)
        else:
            logging.error('/%s is not a registered command.' % command_name)
        