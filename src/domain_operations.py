import os
import re
import subprocess
import sys

from pardus_domain_joiner import domain_joiner_realmd
from pardus_domain_joiner import domain_joiner_winbind
from pardus_domain_joiner import config_manager
from pardus_domain_joiner import update_krb5_config
from pardus_domain_joiner import logger

import locale
from locale import gettext as _

# Development: ../locale, Production: /usr/share/locale
localedir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../locale')
if not os.path.exists(localedir):
    localedir = '/usr/share/locale'

SYSTEM_LANGUAGE = os.environ.get("LANG")
locale.setlocale(locale.LC_ALL, os.environ.get("LANG"))

locale.bindtextdomain('pardus-lib-domain-joiner', localedir)
locale.textdomain('pardus-lib-domain-joiner')

# Logger
logger = logger.get_logger("domain_operations")

def discover_domain(domain):
    process = subprocess.run(["nslookup", domain], capture_output=True, text=True)

    if process.returncode == 0:
        output = process.stdout.strip()
        return output

    return ""


def get_netbios_name(domain):
    result = subprocess.run(["nmblookup", "-A", domain], text=True, capture_output=True)
    netbios = ""

    lines = result.stdout.strip().split("\n")
    for line in lines:
        if "GROUP" in line:
            netbios = line.strip().split("<")[0]
            return netbios.strip()

    return netbios


def eprint(msg):
    # print(msg, file=sys.stderr, flush=True)
    logger.error(msg)

def fail_and_return(msg):
    # print(msg, file=sys.stderr, flush=True)
    logger.error(_("%s"), msg)
    config_manager.restore_hostname()

    return msg


def restore_config_file(restore_files):
    for backup_name, original in restore_files.items():
        config_manager.restore_config_file(backup_name, original)


def format_ou(ouaddress):
    """Check if OU is a valid AD DN (e.g. OU=Users,DC=example,DC=com)."""
    if not ouaddress:
        return False

    # Regex pattern to match a valid AD DN
    pattern = r"^(OU|CN)=[^,]+(,OU=[^,]+)*,DC=[^,]+(,DC=[^,]+)*$"

    return re.match(pattern, ouaddress) is not None


def validate_ou(ouaddress):
    """Return an error for an invalid explicit OU without changing the system."""
    if ouaddress and not format_ou(ouaddress):
        logger.error(_("Organizational Unit format is not correct."))
        logger.info(_("Example: OU=Users,DC=example,DC=com"))
        return _("Organizational Unit format is not correct.")
    return ""


def log_process_output(process, prefix=""):
    if process.stdout:
        logger.info("%s stdout: %s", prefix, process.stdout.strip())

    if process.stderr:
        logger.error("%s stderr: %s", prefix, process.stderr.strip())


def handle_realmd_join(comp_name, domain, user, passwd, ouaddress):
    error = validate_ou(ouaddress)
    if error:
        return error

    restore_files = {"krb5": "/etc/krb5.conf", "sssd": "/etc/sssd/sssd.conf"}

    #print("STEP===Discovering the domain...", flush=True)
    logger.info("STEP===Discovering the domain...")
    if not os.path.isfile("/etc/krb5.conf"):
        return fail_and_return(
            _("krb5.conf not found. Required packages might be missing.")
        )

    try:
        result = domain_joiner_realmd.discover(domain)
        if result:
            #print(_("Domain discovered..."))
            logger.info(_("Domain discovered..."))
        else:
            return fail_and_return(_("Domain not found:") + f" '{domain}'")

    except subprocess.CalledProcessError as e:
        #print(_("Error discovering the domain. Exit Code:"), e.returncode)
        logger.exception(_("Error discovering the domain. Exit Code: %s"), e.returncode)
        return fail_and_return(_("Domain discovery failed."))

    #print("STEP===Backup configuration files...", flush=True)
    logger.info("STEP===Backup configuration files...")

    # If there is a sssd file, take a backup.
    sssd_file = "/etc/sssd/sssd.conf"
    config_manager.backup_config_file(sssd_file, "sssd")

    #print("STEP===Joining the domain with sssd...", flush=True)
    logger.info("STEP===Joining the domain with sssd...")
    process = domain_joiner_realmd.join(domain, user, passwd, ouaddress)
    #print("realmd process stdout:", process.stdout)
    #print("realmd process stderr:", process.stderr)
    log_process_output(process, "sssd-join")

    if process.returncode == 0:
        #print("STEP===Updating configuration files...", flush=True)
        logger.info("STEP===Updating configuration files...")

        config_manager.update_hostname_file(comp_name, domain)
        config_manager.update_hosts_file(comp_name, domain)

        """if smb_settings:
            config_manager.update_samba_conf_for_sssd(domain)"""

        config_manager.update_sssd_conf(domain)

        #print("STEP===Enabling Pardus PAM Config...", flush=True)
        logger.info("STEP===Enabling Pardus PAM Config...")
        subprocess.call(
            ["pam-auth-update", "--enable", "pardus-pam-config"],
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
        )

        #print("STEP===Success.", flush=True)
        logger.info("STEP===Success.")

        #print("This computer has been successfully added to the domain.")
        logger.info("This computer has been successfully added to the domain.")
        return ""

    # Couldn't connect, restore settings
    msg = fail_and_return(process.stderr)

    #print(" ")
    #print(_("=== Restoring Configuration Files from Backup ==="))
    logger.info(_("=== Restoring Configuration Files from Backup ==="))
    restore_config_file(restore_files)

    return msg


def handle_winbind_join(comp_name, domain, user, passwd, ouaddress, workgroup):
    error = validate_ou(ouaddress)
    if error:
        return error

    restore_files = {
        "krb5": "/etc/krb5.conf",
        "samba-winbind": "/etc/samba/smb.conf",
        "nsswitch": "/etc/nsswitch.conf",
    }

    #print("STEP===Discovering the domain...", flush=True)
    logger.info("STEP===Discovering the domain...")
    found_domain = discover_domain(domain)
    if not found_domain:
        return fail_and_return(_("Domain not found:") + f" '{domain}'")

    if not os.path.isfile("/etc/krb5.conf"):
        return fail_and_return(
            _("krb5.conf not found. Required packages might be missing.")
        )

    #print(_("Updating /etc/krb5.conf file..."))
    logger.info(_("Updating /etc/krb5.conf file..."))
    config_manager.backup_config_file("/etc/krb5.conf", "krb5")
    update_krb5_config.update_krb5_conf(domain)
    #print(_("Updated /etc/krb5.conf file..."))
    logger.info(_("Updated /etc/krb5.conf file..."))
    config_manager.update_samba_conf_for_winbind(domain, workgroup)

    p_discover = domain_joiner_winbind.discover()
    if p_discover.returncode != 0:
        #print("discover stdout:", p_discover.stdout, flush=True)
        eprint("discover stderr:" + p_discover.stderr)
        log_process_output(p_discover, "discover")
        restore_config_file(restore_files)
        return fail_and_return(_("Couldn't discovered the domain"))

    #print("STEP===Updating configuration files...", flush=True)
    logger.info("STEP===Updating configuration files...")
    config_manager.update_nsswitch_conf()
    config_manager.update_hostname_file(comp_name, domain)
    config_manager.update_hosts_file(comp_name, domain)

    #print("STEP===Joining the domain with winbind...", flush=True)
    logger.info("STEP===Joining the domain with winbind...")
    process = domain_joiner_winbind.join(user, passwd, ouaddress)
    eprint(process.stderr)
    #print(process.stdout, flush=True)
    log_process_output(process, "winbind-join")

    if process.returncode == 0 and "Joined" in process.stdout:
        domain_user = f"{user}@{domain.upper()}"
        subprocess.run(
            ["kinit", domain_user], input=passwd + "\n", text=True, capture_output=True
        )

        #print(_("Services are starting..."), end="", flush=True)
        logger.info(_("Services are starting..."))
        subprocess.run(["systemctl", "restart", "smbd.service"], capture_output=True)
        subprocess.run(["systemctl", "restart", "nmbd.service"], capture_output=True)
        subprocess.run(["systemctl", "restart", "winbind.service"], capture_output=True)
        #print(_("Done!"))
        logger.info(_("Done!"))

        p_domaininfo = domain_joiner_winbind.domain_info()
        if p_domaininfo.returncode == 0:
            #print(_("This computer has been successfully added to the domain."))
            logger.info(_("This computer has been successfully added to the domain."))
            return ""
        else:
            #print(
            #    "domain_joiner_winbind.domain_info exit code:",
            #    p_domaininfo.returncode,
            #)
            #print(
            #    "domain_joiner_winbind.domain_info stdout:",
            #    p_domaininfo.stdout,
            #)
            #print(
            #    "domain_joiner_winbind.domain_info stderr:",
            #    p_domaininfo.stderr,
            #    flush=True,
            #)
            log_process_output(p_domaininfo, "winbind-domain-info")
            return fail_and_return(p_domaininfo.stdout)

    msg = fail_and_return(process.stdout)

    #print(" ")
    #print(_("=== Restoring Configuration Files from Backup ==="))
    logger.info(_("=== Restoring Configuration Files from Backup ==="))
    restore_config_file(restore_files)

    return msg


def join(
    comp_name,
    domain,
    user,
    passwd,
    ouaddress=None,
    workgroup=None,
    realmd=None,
    winbind=None,
):
    try:
        # GUI and CLI callers must be validated before services or PAM change.
        if realmd or winbind:
            logger.info("STEP===Organizational Unit format check...")
            error = validate_ou(ouaddress)
            if error:
                return error

        # ouaddress = check_ouaddress(ouaddress, domain)
        if realmd:
            #print("STEP===Starting sssd service...", flush=True)
            logger.info("STEP===Starting sssd service...")
            config_manager.start_sssd_service()
            subprocess.run(["pam-auth-update", "--enable", "sss"], capture_output=True)

            return handle_realmd_join(comp_name, domain, user, passwd, ouaddress)
        elif winbind:
            #print("STEP===Starting winbind service...", flush=True)
            logger.info("STEP===Starting winbind service...")
            config_manager.start_winbind_service()
            subprocess.run(["pam-auth-update", "--disable", "sss"], capture_output=True)

            return handle_winbind_join(
                comp_name, domain, user, passwd, ouaddress, workgroup
            )
        else:
            logger.error(_("No domain join method selected. Please specify either realmd or winbind."))
            return _("No domain join method selected. Please specify either realmd or winbind.")

    except subprocess.CalledProcessError as e:
        logger.exception(_("An error occurred during the join process: %s"), e.stderr)
        return _("An error occurred during the join process: {}").format(e.stderr)


def leave(user, password, realmd=None, winbind=None):
    restore_files = {
        "krb5": "/etc/krb5.conf",
        "sssd": "/etc/sssd/sssd.conf",
        "nsswitch": "/etc/nsswitch.conf",
        "samba-winbind": "/etc/samba/smb.conf",
    }

    if not realmd and not winbind:
        return fail_and_return("Please provide connection type, realmd or winbind")

    #print("STEP===Leaving Started...", flush=True)
    logger.info("STEP===Leaving Started...")
    if realmd:
        p = domain_joiner_realmd.leave(user, password)
    elif winbind:
        p = domain_joiner_winbind.leave(user, password)
        #print("STEP===Restarting winbind service...", flush=True)
        logger.info("STEP===Restarting winbind service...")
        subprocess.run(["systemctl", "restart", "winbind.service"], capture_output=True)

    # Success
    if p.returncode == 0:
        #print("STEP===Restoring configuration files...", flush=True)
        logger.info("STEP===Restoring configuration files...")
        restore_config_file(restore_files)
        config_manager.restore_hostname()
        return ""

    return fail_and_return(p.stderr)


def list(realmd=None, winbind=None):
    if realmd:
        process = domain_joiner_realmd.list_realm()
        if process.returncode == 0:
            realm_name = process.stdout.decode("utf-8").split("\n")[0]
            return realm_name
    elif winbind:
        domain_info = domain_joiner_winbind.domain_info()
        if domain_info.returncode == 0:
            process = domain_joiner_winbind.discover()
            lines = process.stdout.splitlines()
            for line in lines:
                if line.startswith("Realm"):
                    realm_name = line.split(":")[1].strip()
                    return realm_name
    return ""
