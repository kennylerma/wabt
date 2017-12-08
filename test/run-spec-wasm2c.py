#!/usr/bin/env python
#
# Copyright 2017 WebAssembly Community Group participants
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from __future__ import print_function
import argparse
try:
  from cStringIO import StringIO
except ImportError:
  from io import StringIO
import json
import os
import struct
import subprocess
import sys

import find_exe
import utils
from utils import Error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

F32_INF = 0x7f800000
F32_NEG_INF = 0xff800000
F32_NEG_ZERO = 0x80000000
F64_INF = 0x7ff0000000000000
F64_NEG_INF = 0xfff0000000000000
F64_NEG_ZERO = 0x8000000000000000


def I32ToC(value):
  return '%su' % value


def I64ToC(value):
  return '%sull' % value


def IsNaNF32(f32_bits):
  return (F32_INF < f32_bits < F32_NEG_ZERO) or (f32_bits > F32_NEG_INF)


def IsNaNF64(f64_bits):
  return (F64_INF < f64_bits < F64_NEG_ZERO) or (f64_bits > F64_NEG_INF)


def ReinterpretF32(f32_bits):
  return struct.unpack('<f', struct.pack('<I', f32_bits))[0]


def ReinterpretF64(f64_bits):
  return struct.unpack('<d', struct.pack('<Q', f64_bits))[0]


def F32ToC(f32_bits):
  if f32_bits == F32_INF:
    return 'INFINITY'
  elif f32_bits == F32_NEG_INF:
    return '-INFINITY'
  elif IsNaNF32(f32_bits):
    return 'make_nan_f32(0x%08x)' % f32_bits
  else:
    return '%sf' % repr(ReinterpretF32(f32_bits))


def F64ToC(f64_bits):
  if f64_bits == F64_INF:
    return 'INFINITY'
  elif f64_bits == F64_NEG_INF:
    return '-INFINITY'
  elif IsNaNF64(f64_bits):
    return 'make_nan_f64(0x%016x)' % f64_bits
  else:
    # Use repr to get full precision
    return repr(ReinterpretF64(f64_bits))


def MangleName(module_name, s):
  result = module_name + 'Z_'
  for c in s:
    if (c.isalnum() and c != 'Z') or c == '_':
      result += c
    else:
      result += 'Z%02X' % ord(c)
  return result


def ModuleIdxName(idx):
  return 'MOD%d_' % idx


# TODO(binji): cleanup
module_names = {}

def AddModuleByName(name, idx):
  module_names[name] = idx

def ModuleName(name):
  return module_names[name]


class CWriter(object):

  def __init__(self, spec_json, prefix, out_file, out_dir):
    self.source_filename = os.path.basename(spec_json['source_filename'])
    self.commands = spec_json['commands']
    self.out_file = out_file
    self.out_dir = out_dir
    self.prefix = prefix
    self.module_idx = 0

  def Write(self):
    self._MaybeWriteDummyModule()
    self._WriteIncludes()
    self.out_file.write(self.prefix)
    self.out_file.write("\nvoid run_spec_tests(void) {\n\n")
    for command in self.commands:
      self._WriteCommand(command)
    self.out_file.write("\n}\n")

  def _MaybeWriteDummyModule(self):
    if not any(True for c in self.commands if c['type'] == 'module'):
      # This test doesn't have any valid modules, so just use a dummy instead.
      filename = utils.ChangeExt(self.source_filename, '-dummy.wasm')
      with open(os.path.join(self.out_dir, filename), 'wb') as wasm_file:
        wasm_file.write(b'\x00\x61\x73\x6d\x01\x00\x00\x00')

      dummy_command = {'type': 'module', 'line': 0, 'filename': filename}
      self.commands.insert(0, dummy_command)

  def _WriteFileAndLine(self, command):
    self.out_file.write('// %s:%d\n' % (self.source_filename, command['line']))

  def _WriteIncludes(self):
    idx = 1
    for command in self.commands:
      if command['type'] == 'module':
        header = os.path.splitext(command['filename'])[0] + '.h'
        self.out_file.write(
            '#define WASM_RT_MODULE_PREFIX %s\n' % self._ModuleIdxName(idx))
        self.out_file.write("#include \"%s\"\n" % header)
        self.out_file.write('#undef WASM_RT_MODULE_PREFIX\n\n')
        idx += 1

  def _WriteCommand(self, command):
    command_funcs = {
        'module': self._WriteModuleCommand,
        'action': self._WriteActionCommand,
        'register': self._WriteRegisterCommand,
        # 'assert_malformed': None,
        # 'assert_invalid': None,
        # 'assert_unlinkable': None,
        # 'assert_uninstantiable': None,
        'assert_return': self._WriteAssertReturnCommand,
        'assert_return_canonical_nan': self._WriteAssertReturnNanCommand,
        'assert_return_arithmetic_nan': self._WriteAssertReturnNanCommand,
        'assert_trap': self._WriteAssertActionCommand,
        'assert_exhaustion': self._WriteAssertActionCommand,
    }

    func = command_funcs.get(command['type'])
    if func is not None:
      self._WriteFileAndLine(command)
      func(command)
      self.out_file.write('\n')

  def _ModuleIdxName(self, idx=None):
    idx = idx or self.module_idx
    return ModuleIdxName(idx)

  def _WriteModuleCommand(self, command):
    self.module_idx += 1
    self.out_file.write('%sinit();\n' % self._ModuleIdxName())

    if 'name' in command:
      AddModuleByName(command['name'], self.module_idx)

  def _WriteActionCommand(self, command):
    self.out_file.write('%s;\n' % self._Action(command['action']))

  def _WriteRegisterCommand(self, command):
    # TODO
    pass

  def _WriteAssertReturnCommand(self, command):
    expected = command['expected']
    if len(expected) == 1:
      assert_map = {
        'i32': 'ASSERT_RETURN_I32',
        'f32': 'ASSERT_RETURN_F32',
        'i64': 'ASSERT_RETURN_I64',
        'f64': 'ASSERT_RETURN_F64',
      }

      type_ = expected[0]['type']
      assert_macro = assert_map[type_]
      self.out_file.write('%s(%s, %s);\n' %
                          (assert_macro,
                           self._Action(command['action']),
                           self._ConstantList(expected)))
    elif len(expected) == 0:
      self._WriteAssertActionCommand(command)
    else:
      raise Error('Unexpected result with multiple values: %s' % expected)

  def _WriteAssertReturnNanCommand(self, command):
    assert_map = {
      ('assert_return_canonical_nan', 'f32'): 'ASSERT_RETURN_CANONICAL_NAN_F32',
      ('assert_return_canonical_nan', 'f64'): 'ASSERT_RETURN_CANONICAL_NAN_F64',
      ('assert_return_arithmetic_nan', 'f32'): 'ASSERT_RETURN_ARITHMETIC_NAN_F32',
      ('assert_return_arithmetic_nan', 'f64'): 'ASSERT_RETURN_ARITHMETIC_NAN_F64',
    }

    expected = command['expected']
    type_ = expected[0]['type']
    assert_macro = assert_map[(command['type'], type_)]

    self.out_file.write('%s(%s);\n' % (assert_macro,
                                       self._Action(command['action'])))

  def _WriteAssertActionCommand(self, command):
    assert_map = {
      'assert_exhaustion': 'ASSERT_EXHAUSTION',
      'assert_return': 'ASSERT_RETURN',
      'assert_trap': 'ASSERT_TRAP',
    }

    assert_macro = assert_map[command['type']]
    self.out_file.write('%s(%s);\n' % (
      assert_macro, self._Action(command['action'])))

  def _Constant(self, const):
    type_ = const['type']
    value = int(const['value'])
    if type_ == 'i32':
      return I32ToC(value)
    elif type_ == 'i64':
      return I64ToC(value)
    elif type_ == 'f32':
      return F32ToC(value)
    elif type_ == 'f64':
      return F64ToC(value)
    else:
      assert False

  def _ConstantList(self, consts):
    return ', '.join(self._Constant(const) for const in consts)

  def _Action(self, action):
    type_ = action['type']

    if 'module' in action:
      module_name = self._ModuleIdxName(ModuleName(action['module']))
    else:
      module_name = self._ModuleIdxName()

    field = MangleName(module_name, action['field'])
    if type_ == 'invoke':
      return '%s(%s)' % (field, self._ConstantList(action.get('args', [])))
    elif type_ == 'get':
      return field
    else:
      raise Error('Unexpected action type: %s' % type_)


# NOTE: still broken
#
# * call_indirect -- stack overflow
# * call          -- stack overflow
# * elem          -- module name registering is broken
# * fac           -- stack overflow
# * func_ptrs     -- need spectest.print
# * imports       -- need overloaded spectest.print
# * linking       -- module name registering is broken
# * memory        -- need spectest.global
# * names         -- weird names??
# * skip-stack-guard-page -- stack overflow?
# * start         -- need spectest.print


def main(args):
  parser = argparse.ArgumentParser()
  parser.add_argument('-o', '--out-dir', metavar='PATH',
                      help='output directory for files.')
  parser.add_argument('-P', '--prefix', metavar='PATH', help='prefix file.',
                      default=os.path.join(SCRIPT_DIR, 'spec-wasm2c-prefix.c'))
  parser.add_argument('--bindir', metavar='PATH',
                      default=find_exe.GetDefaultPath(),
                      help='directory to search for all executables.')
  parser.add_argument('--cc', metavar='PATH',
                      help='the path to the C compiler', default='cc')
  parser.add_argument('--cflags', metavar='FLAGS',
                      help='additional flags for C compiler.',
                      action='append', default=[])
  parser.add_argument('-v', '--verbose', help='print more diagnotic messages.',
                      action='store_true')
  parser.add_argument('--no-error-cmdline',
                      help='don\'t display the subprocess\'s commandline when'
                      + ' an error occurs', dest='error_cmdline',
                      action='store_false')
  parser.add_argument('-p', '--print-cmd',
                      help='print the commands that are run.',
                      action='store_true')
  parser.add_argument('file', help='wast file.')
  options = parser.parse_args(args)

  with utils.TempDirectory(options.out_dir, 'run-spec-wasm2c-') as out_dir:
    # Parse JSON file and generate main .c file with calls to test functions.
    wast2json = utils.Executable(
        find_exe.GetWast2JsonExecutable(options.bindir),
        error_cmdline=options.error_cmdline)
    wast2json.AppendOptionalArgs({'-v': options.verbose})

    json_file_path = utils.ChangeDir(
        utils.ChangeExt(options.file, '.json'), out_dir)
    wast2json.RunWithArgs(options.file, '-o', json_file_path)

    with open(json_file_path) as json_file:
      spec_json = json.load(json_file)

    prefix = ''
    if options.prefix:
      with open(options.prefix) as prefix_file:
        prefix = prefix_file.read() + '\n'

    output = StringIO()
    CWriter(spec_json, prefix, output, out_dir).Write()

    main_filename = utils.ChangeExt(json_file_path,  '-main.c')
    with open(main_filename, 'w') as out_main_file:
      out_main_file.write(output.getvalue())

    # Convert .wasm -> .c
    wasm2c = utils.Executable(
        find_exe.GetWasm2CExecutable(options.bindir),
        error_cmdline=options.error_cmdline)

    module_filenames = [c['filename'] for c in spec_json['commands']
                        if c['type'] == 'module']

    # Compile all .c files to .o files
    cc = utils.Executable(options.cc, *options.cflags)
    o_filenames = []

    i = 1
    for wasm_filename in module_filenames:
      c_filename = utils.ChangeExt(wasm_filename, '.c')
      o_filename = utils.ChangeExt(wasm_filename, '.o')
      o_filenames.append(o_filename)
      wasm2c.RunWithArgs(wasm_filename, '-o', c_filename, cwd=out_dir)
      cc.RunWithArgs('-c', '-o', o_filename,
                     '-DWASM_RT_MODULE_PREFIX=%s' % ModuleIdxName(i),
                     c_filename, cwd=out_dir)
      i += 1

    main_c = os.path.basename(main_filename)
    main_exe = os.path.basename(utils.ChangeExt(json_file_path, ''))
    cc.RunWithArgs('-o', main_exe, '-lm', main_c, *o_filenames, cwd=out_dir)

    utils.Executable(os.path.join(out_dir, main_exe),
                     forward_stdout=True).RunWithArgs()

  return 0


if __name__ == '__main__':
  try:
    sys.exit(main(sys.argv[1:]))
  except Error as e:
    sys.stderr.write(u'%s\n' % e)
    sys.exit(1)