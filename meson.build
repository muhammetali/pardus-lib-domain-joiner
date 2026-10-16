project(
  'pardus-lib-domain-joiner',
  version: '0.1.0',
  license: 'GPL-3.0+',
)

py = import('python').find_installation()

test(
  'join-validation',
  py,
  args: ['-m', 'unittest', 'discover', '-s', meson.current_source_dir() / 'tests', '-v'],
  env: ['LANG=C.UTF-8'],
)

# Install Python source files
py.install_sources(
  [
    'src/__init__.py',
    'src/config_manager.py',
    'src/domain_joiner_ldap.py',
    'src/domain_joiner_realmd.py',
    'src/domain_joiner_winbind.py',
    'src/domain_operations.py',
    'src/update_krb5_config.py',
    'src/logger.py',
  ],
  subdir: 'pardus_domain_joiner',
)

install_data(
  'data/pardus-pam-config', install_dir:'/usr/share/pam-configs', rename:'pardus-domain-joiner'
)

# locale setting
subdir('po')
