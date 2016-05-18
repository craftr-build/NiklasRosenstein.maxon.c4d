# -*- mode: python -*-
# Copyright (C) 2015 Niklas Rosenstein
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from craftr import *
craftr_min_version('0.20.0')

from craftr.path import join, normpath, glob
from craftr.ext import platform
from craftr.ext.compiler import gen_output, gen_objects
from os import environ
import re

is_windows = (platform.name == 'win')
is_osx = (platform.name == 'mac')

if not is_windows and not is_osx:
  raise EnvironmentError('unsupported platform "{0}"'.format(platform.name))

c4d_path = environ.get('maxon.c4d.path', None)
release = int(environ.get('maxon.c4d.release', 0))
debug = environ.get('maxon.c4d.debug', environ.get('debug', False))
mode = 'debug' if debug else 'release'

# =====================================================================
#   Evaluate pre-conditions and detect Cinema 4D path and release
# =====================================================================

if not c4d_path:
  # We assume that the project folder is inside the Cinema 4D
  # plugins directory.
  c4d_path = normpath(join(__file__, '../../..'))

if not release:
  # Try to deduce the release number from the installation path.
  match = re.search('Cinema\s+4D\s+R(\d+)', c4d_path, re.I)
  if not match:
    error('could not determine C4D release number, please specify maxon.c4d.release')
  release = int(match.group(1))
  del match


cxx = platform.cxx
ld = platform.ld
lib = platform.ar

arch = cxx.desc.get('target')

info(cxx.desc.get('version_str'))
info('Cinema 4D R{0} for {1}'.format(release, arch))

resource_dir = join(c4d_path, 'resource')
if release <= 15:
  source_dir = join(resource_dir, '_api')
else:
  source_dir = normpath(c4d_path + '/frameworks/cinema.framework/source')

# =====================================================================
#   Generate source and object file lists and include directories
# =====================================================================

sources = glob(source_dir + '/**/*.cpp')

includes = [
  source_dir,
  source_dir + '/c4d_customgui',
  source_dir + '/c4d_gv',
  source_dir + '/c4d_libs',
  source_dir + '/c4d_misc',
  source_dir + '/c4d_misc/datastructures',
  source_dir + '/c4d_misc/memory',
  source_dir + '/c4d_misc/utilities',
  source_dir + '/c4d_preview',
  source_dir + '/c4d_scaling',
  resource_dir + '/res/description']
if release <= 15:
  includes += glob(resource_dir + '/modules/*/res/description')
  includes += glob(c4d_path + '/modules/*/res/description')
  includes += glob(c4d_path + '/modules/*/*/res/description')
else:
  includes += glob(resource_dir + '/modules/*/description')
includes = normpath(includes)

c4d_framework = Framework('maxon.c4d.',
  include = includes,
  external_libs = [],
)

# =====================================================================
#   Embedded Python support
# =====================================================================

python_ver = None
if release >= 17:
  python_ver = '2.7'
elif release >= 12:
  python_ver = '2.6'

if python_ver:
  if release >= 16:
    python_res = join(resource_dir, 'modules', 'python')
  else:
    python_res = join(resource_dir, 'modules', 'python', 'res')

  if is_windows:
    python_arch = '86' if arch == 'x86' else '64'
    python_fw = join(python_res, 'Python.win' + python_arch + '.framework')
    python_lib = 'python' + python_ver.replace('.', '')
    python_lib_path = join(python_fw, 'libs')
    python_lib_full = join(python_lib_path, python_lib + '.lib')
    python_include = join(python_fw, 'include')

    pylib = Framework(
      include = [python_include, path.local('fix/python_api')],
      libpath = [python_lib_path],
    )
  elif is_osx:
    python_fw = join(python_res, 'Python.osx.framework')
    python_lib = 'Python.osx'
    python_lib_path = python_fw
    python_lib_full = join(python_lib_path, python_lib)
    python_include = join(python_fw, 'include', 'python' + python_ver)

    pylib = Framework(
      include = [python_include, path.local('fix/python_api')],
      external_libs = [python_lib_full],
    )
  else:
    assert False

# =====================================================================
#   Determine application path
# =====================================================================

if is_windows:
  if arch == 'x64':
    if release < 16:
      app = join(c4d_path, 'CINEMA 4D 64 Bit.exe')
    else:
      app = join(c4d_path, 'CINEMA 4D.exe')
  elif arch == 'x86':
    app = join(c4d_path, 'CINEMA 4D.exe')
  else:
    assert False
elif is_osx:
  app = join(c4d_path, 'CINEMA 4D.app/Contents/MacOS/CINEMA 4D')
else:
  assert False

debug_args = ['-debug', '-g_alloc=debug', '-g_console=true']

# =====================================================================
#   Compiler settings
# =====================================================================

def _msvc_objects(sources, frameworks=(), target_name=None, **kwargs):
  assert arch in ('x64', 'x86'), arch
  assert release in range(13, 18)

  builder = TargetBuilder(sources, frameworks, kwargs, name=target_name)
  builder.add_framework(c4d_framework)
  objects = gen_objects(builder.inputs, suffix=platform.obj)

  defines = builder.merge('defines')
  include = builder.merge('include')
  additional_flags = builder.merge('additional_flags')
  additional_flags += builder.merge('msvc_additional_flags')
  msvc_runtime_library = builder.get('msvc_runtime_library', None)
  legacy_api = builder.get('legacy_api', False)
  exceptions = builder.get('exceptions', False)
  autodeps = builder.get('autodeps', True)
  forced_include = builder.merge('forced_include')

  defines += ['__PC']
  if release >= 15:
    defines += ['MAXON_API', 'MAXON_TARGET_WINDOWS']
    defines += ['MAXON_TARGET_DEBUG'] if debug else ['MAXON_TARGET_RELEASE']
    if arch == 'x64':
      defines += ['MAXON_TARGET_64BIT']
  else:
    defines += ['_DEBUG', 'DEBUG'] if debug else ['NDEBUG']
    if arch == 'x64':
      defines += ['__C4D_64BIT', 'WIN64', '_WIN64']
    else:
      defines += ['WIN32', '_WIN32']
  if legacy_api:
    defines += ['__LEGACY_API']

  command = [cxx['program']] + ('/nologo /c /W4 /WX- /MP /Gm- /Gs /Gy- '
    '/fp:precise /Zc:wchar_t- /Gd /TP /wd4062 /wd4100 /wd4127 /wd4131 '
    '/wd4201 /wd4210 /wd4242 /wd4244 /wd4245 /wd4305 /wd4310 /wd4324 '
    '/wd4355 /wd4365 /wd4389 /wd4505 /wd4512 /wd4611 /wd4706 /wd4718 '
    '/wd4740 /wd4748 /wd4996 /FC /errorReport:prompt /vmg /vms /w44263 '
    '/we4264').split()
  if cxx.version >= '18':
    # required for parallel writes to .pdb files.
    command += ['/FS']

  if autodeps:
    command += ['/showIncludes']
    builder.target['deps'] = 'msvc'
    builder.target['msvc_deps_prefix'] = cxx.deps_prefix

  if msvc_runtime_library is None:
    msvc_runtime_library = 'static' if release <= 15 else 'dynamic'
  if msvc_runtime_library == 'dynamic':
    command += ['/MTd' if debug else '/MT']
  elif msvc_runtime_library == 'static':
    command += ['/MDd' if debug else '/MD']
  else:
    raise ValueError('invalid msvc_runtime_library: {0!r}'.format(msvc_runtime_library))

  if debug:
    command += ['/Od', '/Zi', '/RTC1']
  else:
    command += ['/Ox', '/Oy-', '/Oi', '/Ob2', '/Ot', '/GF']

  if exceptions:
    command += ['/EHsc']

  command += ['/D' + x for x in defines]
  command += ['/I' + x for x in include]
  command += ['/FI' + x for x in forced_include]
  command += additional_flags
  command += ['$in', '/Fo$out']

  return builder.create_target(command, outputs=objects, foreach=True)


def _msvc_staticlib(output, inputs, frameworks=(), target_name=None, **kwargs):
  builder = TargetBuilder(inputs, frameworks, kwargs, name=target_name)
  output = gen_output(output, suffix=platform.lib)

  # Write the names of the input files to a file to avoid too
  # long command lines.
  cmdfile = builder.write_command_file(builder.inputs, '.in')

  # Generate the command.
  command = [lib['program'], '/nologo', '/OUT:$out', '@' + cmdfile]
  command += builder.merge('additional_flags')
  return builder.create_target(command, outputs=[output])


def _msvc_link(output, inputs, frameworks=(), target_name=None, **kwargs):
  builder = TargetBuilder(inputs, frameworks, kwargs, name=target_name)

  external_libs = builder.merge('external_libs')
  external_libs = builder.expand_inputs(external_libs)

  output_type = builder.get('output_type', 'dll')
  additional_flags = builder.merge('additional_flags')
  additional_flags += builder.merge('msvc_additional_flags')
  libs = builder.merge('libs')
  libs += builder.merge('msvc_libs')
  libs += builder.merge('win_libs')
  if arch == 'x86':
    libs += builder.merge('win32_libs')
  else:
    libs += builder.merge('win64_libs')
  libpath = builder.merge('libpath')

  if output_type not in ('bin', 'dll'):
    raise ValueError('invalid output_type: {0!r}'.format(output_type))
  if output_type == 'dll':
    suffix = lambda x: path.addsuffix(x, '.cdl64' if arch == 'x64' else '.cdl')
  else:
    suffix = getattr(platform, output_type)

  infile = builder.write_command_file(builder.inputs, '.in')

  output = gen_output(output, suffix=suffix)
  command = [ld['program'], '/nologo', '/OUT:$out']
  if output_type == 'dll':
    command += ['/DLL']
  if debug:
    command += ['/debug']
  command += path.addsuffix(libs, '.lib')
  command += external_libs
  command += ['/LIBPATH:' + x for x in libpath]
  command += additional_flags
  command += ['@' + infile]

  _update_deps(output)
  return builder.create_target(command, outputs=[output], implicit_deps=external_libs)


def _clang_get_stdlib():
  return 'libstdc++' if release <= 15 else 'libc++'


def _clang_objects(sources, frameworks=(), target_name=None, **kwargs):
  assert arch.startswith('x86_64'), arch
  assert release in range(13, 18)
  builder = TargetBuilder(sources, frameworks, kwargs, name=target_name)
  builder.add_framework(c4d_framework)
  objects = gen_objects(builder.inputs, suffix=platform.obj)

  defines = builder.merge('defines')
  include = builder.merge('include')
  additional_flags = builder.merge('additional_flags')
  additional_flags += builder.merge('clang_additional_flags')
  remove_flags = builder.merge('remove_flags')
  remove_flags += builder.merge('clang_remove_flags')
  legacy_api = builder.get('legacy_api', False)
  exceptions = builder.get('exceptions', False)
  autodeps = builder.get('autodeps', True)
  stdlib = builder.get('stdlib', _clang_get_stdlib())
  forced_include = builder.merge('forced_include')

  defines += ['C4D_COCOA', '__MAC']
  if release >= 15:
    defines += ['MAXON_API', 'MAXON_TARGET_OSX']
    defines += ['MAXON_TARGET_DEBUG'] if debug else ['MAXON_TARGET_RELEASE']
    defines += ['MAXON_TARGET_64BIT']
  else:
    defines += ['_DEBUG', 'DEBUG'] if defines else ['NDEBUG']
    defines += ['__C4D_64BIT']
  if legacy_api:
    defines += ['__LEGACY_API']

  command = [cxx['program'], '-c']
  if release <= 15:
    command += (
      '-fmessage-length=0 -fdiagnostics-show-note-include-stack '
      '-fmacro-backtrace-limit=0 -std=c++11 -Wno-trigraphs '
      '-fno-rtti -fpascal-strings '
      '-Wno-missing-field-initializers -Wno-missing-prototypes '
      '-Wno-non-virtual-dtor -Woverloaded-virtual -Wno-exit-time-destructors '
      '-Wmissing-braces -Wparentheses -Wno-switch -Wunused-function '
      '-Wunused-label -Wno-unused-parameter -Wunused-variable -Wunused-value '
      '-Wno-empty-body -Wno-uninitialized -Wunknown-pragmas -Wno-shadow '
      '-Wno-four-char-constants -Wno-conversion -Wno-constant-conversion '
      '-Wno-int-conversion -Wno-bool-conversion -Wno-enum-conversion '
      '-Wno-shorten-64-to-32 -Wno-newline-eof -Wno-c++11-extensions '
      '-fasm-blocks -fstrict-aliasing -Wdeprecated-declarations '
      '-Wno-invalid-offsetof -mmacosx-version-min=10.6 -msse3 '
      '-fvisibility=hidden -fvisibility-inlines-hidden -Wno-sign-conversion '
      '-Wno-logical-op-parentheses -fno-math-errno').split()
  else:
    command += (
      '-fmessage-length=0 -fdiagnostics-show-note-include-stack '
      '-fmacro-backtrace-limit=0 -std=c++11 -Wno-trigraphs '
      '-fno-rtti -fpascal-strings -Wmissing-field-initializers '
      '-Wmissing-prototypes -Wdocumentation -Wno-non-virtual-dtor '
      '-Woverloaded-virtual -Wno-exit-time-destructors -Wmissing-braces '
      '-Wparentheses -Wno-switch -Wunused-function -Wunused-label '
      '-Wno-unused-parameter -Wunused-variable -Wunused-value -Wempty-body '
      '-Wuninitialized -Wunknown-pragmas -Wshadow -Wno-four-char-constants '
      '-Wno-conversion -Wconstant-conversion -Wint-conversion '
      '-Wbool-conversion -Wenum-conversion -Wsign-compare -Wshorten-64-to-32 '
      '-Wno-newline-eof -Wno-c++11-extensions -fasm-blocks -fstrict-aliasing '
      '-Wdeprecated-declarations -Winvalid-offsetof -mmacosx-version-min=10.7 '
      '-msse3 -fvisibility=hidden -fvisibility-inlines-hidden '
      '-Wno-sign-conversion -fno-math-errno').split()

  if not exceptions:
    command += ['-fno-exceptions']

  if release <= 15:
    if debug:
      command += ['-include', join(source_dir, 'ge_mac_debug_flags.h')]
    else:
      command += ['-include', join(source_dir, 'ge_mac_flags.h')]

  command += ['-stdlib={}'.format(stdlib)]
  command += ['-g', '-O0'] if debug else ['-O3']
  command += ['-D' + x for x in defines]
  command += ['-I' + x for x in include]
  command += utils.flatten(('-include', x) for x in forced_include)
  command += additional_flags

  if autodeps:
    builder.target['depfile'] = '$out.d'
    builder.target['deps'] = 'gcc'
    command += ['-MMD', '-MF', '$depfile']
  command += ['-c', '$in', '-o', '$out']

  # Remove the specified flags and keep every flag that could not
  # be removed from the command.
  remove_flags = set(remove_flags)
  for flag in list(remove_flags):
    count = 0
    while True:
      try:
        command.remove(flag)
      except ValueError:
        break
      count += 1
    if count != 0:
      remove_flags.remove(flag)
  if remove_flags:
    fmt = ' '.join(shell.quote(x) for x in remove_flags)
    builder.log('warn', "flags not removed: {0}".format(fmt))

  builder.add_framework(builder.name, libs=['c++'])
  return builder.create_target(command, outputs=objects, foreach=True)


def _clang_staticlib(output, inputs, frameworks=(), target_name=None, **kwargs):
  builder = TargetBuilder(inputs, frameworks, kwargs, name=target_name)
  output = gen_output(output, suffix=platform.lib)

  command = [lib['program'], 'rcs']
  command += builder.merge('additional_flags')
  command += ['$out', '$in']
  return builder.create_target(command, outputs=[output])


def _clang_link(output, inputs, frameworks=(), target_name=None, **kwargs):
  builder = TargetBuilder(inputs, frameworks, kwargs, name=target_name)

  output_type = builder.get('output_type', 'dll')
  stdlib = builder.get('stdlib', _clang_get_stdlib())
  debug = builder.get('debug', False)
  libs = builder.merge('libs')
  libs += builder.merge('clang_libs')
  libs += builder.merge('osx_libs')
  external_libs = builder.merge('external_libs')
  additional_flags = builder.merge('additional_flags')

  assert output_type in ('bin', 'dll')
  output = gen_output(output, suffix=getattr(platform, output_type))
  command = [ld['program'], '-stdlib=' + stdlib]
  command += ['-shared'] if output_type == 'dll' else []
  command += ['-g'] if debug else []
  command += ['-l' + x for x in libs]
  command += external_libs
  command += additional_flags
  command += ['$in', '-o', '$out']

  _update_deps(output)
  return builder.create_target(command, outputs=[output], implicit_deps=external_libs)


if is_windows:
  objects = _msvc_objects
  staticlib = _msvc_staticlib
  link = _msvc_link
elif is_osx:
  objects = _clang_objects
  staticlib = _clang_staticlib
  link = _clang_link
else:
  assert False


object_files = objects(
  sources = sources,
)

library = staticlib(
  output = 'c4dsdk-r{0}-{1}'.format(release, mode),
  inputs = object_files,
)
c4d_framework['external_libs'] += library.outputs

run = Target(
  command = [app] + debug_args,
  pool = 'console',
  explicit = True,
)

if is_windows:
  run.command = ['cmd', '/c', 'start', shell.safe('"parentconsole"')] + run.command

if is_osx:
  lldb = Target(
    command = ['lldb', '--', app],
    pool = 'console',
    explicit = True,
  )



def _update_deps(path):
  run.order_only_deps.append(path)
  if 'lldb' in globals():
    run.order_only_deps.append(path)
