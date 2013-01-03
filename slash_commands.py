#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
from constants import g

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

MAX_COMMAND_LENGTH = 20


class ExecutionError(Exception):
    pass

class PermissionError(Exception): #(admin, participant, observer)
    pass

class ArgFormatError(Exception):
    pass


class SlashCommand(object):
    def __init__(self, command_name, text_arg_format, text_description, validate_sender, transform_args, action):
        self._command_name = command_name
        self._text_arg_format = text_arg_format
        self._text_description = text_description
        self.validate_sender = validate_sender
        self.transform_args = transform_args  # should return the args as a list if they are valid. an empty arg list shouldn't raise an error!
        self._action = action
    
    def execute(self, sender, arg_string, vinebot):
        if not self.validate_sender(sender, vinebot):
            raise PermissionError
        # pass the command_name to to transform_args so that it can be properly logged
        # and the sender in case the args depend on it or in case it *should* be an arg
        # and the recipient so that the leaf can figure out which vinebot this command was for
        # and the original string in case not all of the tokens in the list should be treated as individual arguments
        # and the tokenized args, all converted to lowercase (.split(' ') returns arrays with '' as an element, so filter those out)
        # note that, if successful, this will also return the parent_command_id, to be used by the command's action method
        arg_tokens = [arg.lower() for arg in filter(lambda arg: arg != '', arg_string.split(' '))]
        args = self.transform_args(self.name, sender, vinebot, arg_string, arg_tokens)
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
        
    def parse_command(self, message):
        message = message.strip().lstrip('/')
        command_name, _, arg_string = message.partition(' ')
        if len(command_name) > MAX_COMMAND_LENGTH:
            g.logger.warning("Max command length of %d exceeded: %s" % (MAX_COMMAND_LENGTH, message))
            if len(arg_string) > 0:
                arg_string = command_name[MAX_COMMAND_LENGTH:] + ' ' + arg_string
            else:
                arg_string = command_name[MAX_COMMAND_LENGTH:]
            command_name = command_name[:MAX_COMMAND_LENGTH]  # re-assign command name after setting arg_string
        return command_name.lower(), arg_string
    
    def handle_command(self, sender, message, vinebot):
        command_name, arg_string = self.parse_command(message)
        if command_name in self.slash_commands:
            slash_command = self.slash_commands[command_name]
            try: 
                parent_command_id, result_message = slash_command.execute(sender, arg_string, vinebot)
                if result_message is not None:  # this way we can return an empty string to send no response
                    return parent_command_id, result_message
                else:
                    return parent_command_id, 'Your /%s command was successful.' % slash_command.name
            except ExecutionError, error:
                parent_command_id, result_message = error
                return parent_command_id, 'Sorry, %s' % result_message
            except PermissionError:
                return None, 'Sorry, you don\'t have permission to use this command.'
            except ArgFormatError:
                return None, 'Sorry, that format wasn\'t quite right. Try:\n\t/%s %s' % \
                    (slash_command.name, slash_command.arg_format)
        elif command_name == 'help':
            command_string = ''
            for slash_command in self.slash_commands.values():
                if slash_command.validate_sender(sender, vinebot):
                    if slash_command.arg_format == '':
                        command_string += '\t/%s: %s\n' % (slash_command.name, slash_command.description)
                    else:
                        command_string += '\t/%s %s: %s\n' % (slash_command.name, slash_command.arg_format, slash_command.description)
            if command_string == '':
                return None, 'You do not have permission to send any commands to this vinebot.'
            else:
                return None, 'The available commands are:\n' + command_string
        else:
            return None, 'Sorry, /%s isn\'t a registered command. Type /help to see a full list.' % command_name
    
    def add(self, slash_command):
        if slash_command.name in self.slash_commands:
            g.logger.error('/%s is already a registered command.' % slash_command.name)
        elif slash_command.name == 'help':
            g.logger.error('The /help command is built in and can not be added.' % slash_command.name)
        else:
            self.slash_commands[slash_command.name] = slash_command
    
    def remove(self, command_name):
        if command_name in self.slash_commands:
            del self.slash_commands[command_name]
        elif command_name == 'help':
            g.logger.error('The /help command is built-in and can not be removed.' % command_name)
        else:
            g.logger.error('/%s is not a registered command.' % command_name)
    
