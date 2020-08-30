"""
The setup file for packaging TickBot
"""
import glob
import os
import pathlib
import shlex
import subprocess as sub
import sys
import tempfile
from setuptools import setup, find_packages, Command

import tick

ROOT = os.path.abspath(os.path.dirname(__file__))
if os.path.dirname(__file__) == '':
    ROOT = os.getcwd()


def make_get_input():
    """
    Simple wrapper to get input from user.
    When --yes in sys.argv, skip input and assume yes to any request.
    """
    try:
        in_func = raw_input
    except NameError:
        in_func = input

    default = False
    if '--yes' in sys.argv:
        sys.argv.remove('--yes')
        default = True

    def inner_get_input(msg):
        """
        The actual function that emulates input.
        """
        if default:
            return 'yes'

        return in_func(msg)
    inner_get_input.default = default

    return inner_get_input


get_input = make_get_input()


class Clean(Command):
    """
    Equivalent of make clean.
    """
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        root = pathlib.Path(ROOT)

        # Ignore .pyc files in .tox as whole dir will be removed,
        # dramaticly reduces list of paths for ease of reading.
        rm_list = [file for file in root.glob('**/*.pyc')
                   if root / '.tox' not in file.parents]
        rm_list += list(root.glob('*.egg-info'))
        rm_list += list(root.glob('*.egg'))
        rm_list += list(root.rglob('*diagram.png'))
        rm_list.append(root / '.eggs')
        rm_list.append(root / '.tox')
        rm_list.append(root / 'build')
        rm_list.append(root / 'dist')

        print("Removing:")
        for path in rm_list:
            print("\t{}".format(path))
        recv = get_input('OK? y/n  ').strip().lower()
        if recv.startswith('y'):
            sub.run(['rm', '-vrf'] + [str(f) for f in rm_list])


class InstallDeps(Command):
    """
    Install dependencies to run & test.
    """
    description = "Install the depencies for the project."
    user_options = [
        ('force=', None, "Bypass prompt."),
    ]

    def initialize_options(self):
        self.force = None

    def finalize_options(self):
        pass

    def run(self):
        print('Installing/Upgrading runtime & testing dependencies')
        cmd = 'pip install -U ' + ' '.join(RUN_DEPS + TEST_DEPS)
        print('Executing: ' + cmd)
        if self.force:
            recv = self.force
        else:
            recv = get_input('OK? y/n  ').strip().lower()
        if recv.startswith('y'):
            timeout = 150
            try:
                sub.run(shlex.split(cmd), check=True, timeout=timeout)
            except sub.TimeoutExpired:
                print('Deps installation took over {} seconds, something is wrong.'.format(timeout))
            except sub.CalledProcessError:
                print("Error during pip installation, check pip.")


class Test(Command):
    """
    Run the tests and track coverage.
    """
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def check_prereqs(self):
        """
        Checks required programs.
        """
        cap = sub.run(shlex.split('python -m pytest --trace-config --co'),
                      stdout=sub.PIPE, stderr=sub.STDOUT)
        stdout = cap.stdout.decode()
        print(stdout)
        if 'pytest-cov' not in stdout:
            print('Please run: python setup.py deps')
            sys.exit(1)

    def run(self):
        self.check_prereqs()
        old_cwd = os.getcwd()

        try:
            os.chdir(ROOT)
            sub.run(shlex.split('python -m pytest --cov=tick --cov=tickdb'), check=True)
        finally:
            os.chdir(old_cwd)


class Coverage(Command):
    """
    Run the tests, generate the coverage html report and open it in your browser.
    """
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def check_prereqs(self):
        """
        Checks required programs.
        """
        try:
            cap = sub.run(shlex.split('python -m pytest --trace-config --co'),
                          stdout=sub.PIPE, stderr=sub.STDOUT, check=True)
            stdout = cap.stdout.decode()
            if 'pytest-cov' not in stdout:
                raise sub.CalledProcessError

            sub.run(shlex.split('coverage --version'),
                    stdout=sub.DEVNULL, stderr=sub.DEVNULL, check=True)
        except sub.CalledProcessError:
            print('Please run: python setup.py deps')
            sys.exit(1)

    def run(self):
        self.check_prereqs()
        old_cwd = os.getcwd()
        cov_dir = os.path.join(tempfile.gettempdir(), 'TickCoverage')
        report = os.path.join(cov_dir, 'index.html')
        cmds = [
            'python -m pytest --cov=tick --cov=tickdb',
            'coverage html -d ' + cov_dir,
            'xdg-open ' + report,
        ]

        try:
            os.chdir(ROOT)
            for cmd in cmds:
                sub.run(shlex.split(cmd), check=True)
            print("Final report available at: ", report)
        except sub.CalledProcessError:
            print("Error occurred running: {}".format(cmd))
            sys.exit(1)
        finally:
            os.chdir(old_cwd)


class UMLDocs(Command):
    """
    Generate UML class and module diagrams.
    """
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def check_prereqs(self):
        """
        Checks required programs.
        """
        try:
            sub.run(shlex.split('pyreverse -h'),
                    stdout=sub.DEVNULL, stderr=sub.DEVNULL, check=True)
        except sub.CalledProcessError:
            print('Please run: python setup.py deps')
            sys.exit(1)
        try:
            sub.run(shlex.split('dot -V'),
                    stdout=sub.DEVNULL, stderr=sub.DEVNULL, check=True)
        except (sub.CalledProcessError, OSError):
            print('Missing graphviz library (dot). Please run:')
            print('sudo apt-get install graphviz')
            sys.exit(1)

    def run(self):
        self.check_prereqs()
        old_cwd = os.getcwd()
        diagrams = []
        cmds = [
            'pyreverse tick',
            'dot -Tpng classes.dot -o ./extras/tick_class_diagram.png',
            'pyreverse tickdb',
            'dot -Tpng classes.dot -o ./extras/tickdb_class_diagram.png',
            'pyreverse tick tickdb',
            'dot -Tpng packages.dot -o ./extras/overall_module_diagram.png',
        ]

        try:
            os.chdir(ROOT)
            for cmd in cmds:
                sub.call(shlex.split(cmd))
            diagrams = [os.path.abspath(pic) for pic in glob.glob('extras/*diagram.png')]
        finally:
            for fname in glob.glob('*.dot'):
                os.remove(fname)
            os.chdir(old_cwd)

        print('\nDiagrams generated:')
        print('  ' + '\n  '.join(diagrams))


SHORT_DESC = 'A simple ticket bot.'
MY_NAME = 'Jeremy Pallats / starcraft.man'
MY_EMAIL = 'N/A'
# Sanic stuck on 0.6.0, 0.7.0 wants websockets >4.0 but discord.py wants <4.0
RUN_DEPS = ['aiofiles', 'argparse', 'cffi', 'decorator', 'discord.py',
            'ijson', 'msgpack-python', 'pymysql', 'pyyaml', 'SQLalchemy', 'uvloop']
TEST_DEPS = ['coverage', 'flake8', 'aiomock', 'mock', 'pylint', 'pytest', 'pytest-asyncio',
             'pytest-cov', 'sphinx', 'tox']
setup(
    name='Tickbot',
    version=tick.__version__,
    description=SHORT_DESC,
    long_description=SHORT_DESC,
    url='https://github.com/starcraftman/tickBot',
    author=MY_NAME,
    author_email=MY_EMAIL,
    maintainer=MY_NAME,
    maintainer_email=MY_EMAIL,
    license='BSD',
    platforms=['any'],

    # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Framework :: AsyncIO',
        'Framework :: Pytest',
        'Intended Audience :: Developers',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Operating System :: POSIX :: Linux',
        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ],

    # What does your project relate to?
    keywords='development',

    # You can just specify the packages manually here if your project is
    # simple. Or you can use find_packages().
    # packages=find_packages(exclude=['venv', 'test*']),
    packages=find_packages(exclude=['venv', '.tox']),

    # List run-time dependencies here.  These will be installed by pip when
    # your project is installed. For an analysis of "install_requires" vs pip's
    # requirements files see:
    # https://packaging.python.org/en/latest/requirements.html
    install_requires=RUN_DEPS,

    tests_require=TEST_DEPS,

    # # List additional groups of dependencies here (e.g. development
    # # dependencies). You can install these using the following syntax,
    # # for example:
    # # $ pip install -e .[dev,test]
    extras_require={
        'test': TEST_DEPS,
    },

    # include_package_data=True,
    # # If there are data files included in your packages that need to be
    # # installed, specify them here.  If using Python 2.6 or less, then these
    # # have to be included in MANIFEST.in as well.
    # package_dir={'tick' : 'tick'},
    # package_data={
    #     'tick': ['.secrets/*']
    # },

    # # Although 'package_data' is the preferred approach, in some case you may
    # # need to place data files outside of your packages. See:
    # # http://docs.python.org/3.4/distutils/setupscript.html#installing-additional-files # noqa
    # # In this case, 'data_file' will be installed into '<sys.prefix>/my_data'
    # data_files=[('secrets', ['tick/secrets/*'])],

    # To provide executable scripts, use entry points in preference to the
    # "scripts" keyword. Entry points provide cross-platform support and allow
    # pip to create the appropriate form of executable for the target platform.
    # entry_points={
    #     'console_scripts': [
    #         'tickbot = tick.bot:main',
    #     ],
    # },

    cmdclass={
        'clean': Clean,
        'coverage': Coverage,
        'deps': InstallDeps,
        'test': Test,
        'uml': UMLDocs,
    }
)
