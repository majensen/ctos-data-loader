import logging
import os, sys
import uuid
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
import re
from configparser import ConfigParser
import yaml
import subprocess
from urllib.parse import urlparse

def get_logger(name):
    formatter = logging.Formatter('%(asctime)s %(levelname)s: (%(name)s) - %(message)s')
    # formatter = logging.Formatter('[%(levelname)s] %(module)s - %(message)s')
    log_level = os.environ.get('DL_LOG_LEVEL', 'INFO')
    log = logging.getLogger(name)
    log.setLevel(log_level)
    std_handler = logging.StreamHandler()
    std_handler.setFormatter(formatter)
    log.addHandler(std_handler)
    return log

def get_uuid_for_node(node_type, signature):
    """Generate V5 UUID for a node
    Arguments:
        node_type - a string represents type of a node, e.g. case, study, file etc.
        signature - a string that can uniquely identify a node within it's type, e.g. case_id, clinical_study_designation etc.
                    or a long string with all properties and values concat together if no id available

    """
    log = get_logger('Utils')
    icdc_base_uuid = uuid.uuid5(uuid.NAMESPACE_URL, ICDC_DOMAIN)
    # log.debug('Base UUID: {}'.format(icdc_base_uuid))
    type_uuid = uuid.uuid5(icdc_base_uuid, node_type)
    # log.debug('Type UUID: {}'.format(type_uuid))
    node_uuid = uuid.uuid5(type_uuid, signature)
    log.debug('Node UUID: {}'.format(node_uuid))
    return str(node_uuid)


def removeTrailingSlash(uri):
    if uri.endswith('/'):
        return re.sub('/+$', '', uri)
    else:
        return uri

def is_parent_pointer(field_name):
    return re.fullmatch(r'\w+\.\w+', field_name) is not None

def send_mail(subject, contents, attachments=None):
    """Sends an email to the provided recipient

    Arguments:
        - sender {string} -- The sender of the email
        - recipient {string} -- The recipient of the email, can be ',' separated if multiple recipient
        - subject {string} -- The email's subject
        - contents {string} -- The email's contents

    Keyword Arguments:
        - attachments {string[]} -- Filenames of attachments (default: {None})
    """
    server = None
    log = get_logger('Utils')
    try:
        message = MIMEMultipart()
        message['Subject'] = subject
        message['From'] = SENDER_EMAIL
        message['To'] = ADMIN_EMAILS

        # set text for message
        contents = contents if isinstance(contents, str) else contents.encode('utf-8')
        message.attach(MIMEText(contents, 'html', 'utf-8'))

        # add attachments to message
        if attachments is not None:
            for attachment in attachments:
                with open(attachment, 'rb') as _file:
                    message.attach(MIMEApplication(
                        _file.read(),
                        Name=os.path.basename(attachment)
                    ))
        # send email
        server = smtplib.SMTP(MAIL_SERVER)
        server.sendmail(SENDER_EMAIL, ADMIN_EMAILS.split(','), message.as_string())
        return True
    except Exception as e:
        log.error(e)
        return False
    finally:
        if server and getattr(server, 'quit'):
            server.quit()


def backup_neo4j(backup_dir, name, address, log):
    try:
        restore_cmd = 'To restore DB from backup (to remove any changes caused by current data loading, run following commands:\n'
        restore_cmd += '#' * 160 + '\n'
        neo4j_cmd = 'neo4j-admin restore --from={}/{} --force'.format(BACKUP_FOLDER, name)
        cmds = [
                  [
                      'mkdir',
                      '-p',
                      backup_dir
                  ],
                  [
                      'neo4j-admin',
                      'backup',
                      '--backup-dir={}'.format(backup_dir),
                      '--name={}'.format(name),
                  ]
               ]
        if address in ['localhost', '127.0.0.1']:
            restore_cmd += '\t$ neo4j stop && {} && neo4j start\n'.format(neo4j_cmd)
            for cmd in cmds:
                log.info(cmd)
                subprocess.call(cmd)
        else:
            second_cmd = 'sudo systemctl stop neo4j && {} && sudo systemctl start neo4j && exit'.format(neo4j_cmd)
            restore_cmd += '\t$ echo "{}" | ssh -t {} sudo su - neo4j\n'.format(second_cmd, address)
            for cmd in cmds:
                remote_cmd = ['ssh', address] + cmd
                log.info(' '.join(remote_cmd))
                subprocess.call(remote_cmd)
        restore_cmd += '#' * 160
        return restore_cmd
    except Exception as e:
        log.exception(e)
        return False

def get_host(uri):
    parts = urlparse(uri)
    return parts.hostname

def check_schema_files(schemas, log):
    if not schemas:
        log.error('Please specify schema file(s) with -s or --schema argument')
        return False

    for schema_file in schemas:
        if not os.path.isfile(schema_file):
            log.error('{} is not a file'.format(schema_file))
            return False
    return True

config = ConfigParser()
CONFIG_FILE_ENV_VAR = 'ICDC_DATA_LOADER_CONFIG'
config_file = os.environ.get(CONFIG_FILE_ENV_VAR, 'config.ini')
if config_file and os.path.isfile(config_file):
    config.read(config_file)
else:
    util_log = get_logger('Utils')
    util_log.error('Can\'t find configuration file! Make a copy of config.sample.ini to config.ini'
                   + ' or specify config file in Environment variable {}'.format(CONFIG_FILE_ENV_VAR))
    sys.exit(1)

PROP_FILE_ENV_VAR = 'ICDC_DATA_LOADER_PROP'
property_file = os.environ.get(PROP_FILE_ENV_VAR, 'props.yml')
util_log = get_logger('Utils')
if property_file and os.path.isfile(property_file):
    with open(property_file) as prop_file:
        PROPS = yaml.safe_load(prop_file)['Properties']
        if not PROPS:
            util_log.error('Can\'t read property file!')
            sys.exit(1)
else:
    util_log.error('Can\'t find property file! Get a copy of prop.yml or specify property file in Environment variable {}'.format(PROP_FILE_ENV_VAR))
    sys.exit(1)

LOG_LEVEL = os.environ.get('DL_LOG_LEVEL', config.get('log', 'log_level'))
ICDC_DOMAIN = config.get('main', 'domain')
QUEUE_LONG_PULL_TIME = int(config.get('sqs', 'long_pull_time'))
VISIBILITY_TIMEOUT = int(config.get('sqs', 'visibility_timeout'))
PSWD_ENV = 'NEO_PASSWORD'
MAIL_SERVER = config.get('mail', 'server')
ADMIN_EMAILS = config.get('mail', 'admin')
SENDER_EMAIL = config.get('mail', 'sender')
NODES_CREATED = 'nodes_created'
RELATIONSHIP_CREATED = 'relationship_created'
BLOCK_SIZE = 65536
TEMP_FOLDER = config.get('main', 'temp_folder')
BACKUP_FOLDER = config.get('main', 'backup_folder')
INDEXD_GUID_PREFIX = config.get('indexd', 'GUID_prefix')
INDEXD_MANIFEST_EXT = config.get('indexd', 'ext')
if not INDEXD_MANIFEST_EXT.startswith('.'):
    INDEXD_MANIFEST_EXT = '.' + INDEXD_MANIFEST_EXT
os.makedirs(BACKUP_FOLDER, exist_ok=True)
if not os.path.isdir(BACKUP_FOLDER):
    util_log.error('{} is not a folder!'.format(BACKUP_FOLDER))
    sys.exit(1)
DATE_FORMAT = '%Y-%m-%d'
DATETIME_FORMAT = '%Y%m%d-%H%M%S'
RELATIONSHIP_TYPE = 'relationship_type'
MULTIPLIER = 'Mul'
DEFAULT_MULTIPLIER = 'many_to_one'
ONE_TO_ONE = 'one_to_one'
UUID = 'uuid'
NEW_MODE = 'new'
UPSERT_MODE = 'upsert'
DELETE_MODE = 'delete'
