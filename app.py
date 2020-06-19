# ----------------------------------------------------------------------------#
# Imports
# ----------------------------------------------------------------------------#

import datetime
import glob
import json
import logging
import os
import subprocess
import tempfile
import uuid
from logging import Formatter, FileHandler

import prediction_models
from flask import Flask, render_template, request, jsonify, url_for, redirect
from rawapi import new_raw_client, RawException, Unauthorized

# ----------------------------------------------------------------------------#
# App Config.
# ----------------------------------------------------------------------------#

app = Flask(__name__)
app.config.from_object('config')

logging.basicConfig(
    level='INFO'
)


def with_login(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except RawException as ex:
            if 'rawcli login' in str(ex):
                subprocess.call(['rawcli', 'login'])
                return func(*args, **kwargs)
            else:
                raise ex
        except Unauthorized:
            subprocess.call(['rawcli', 'login', '-f'])
            return func(*args, **kwargs)

    return wrapper


@with_login
def get_client():
    return new_raw_client()


client = get_client()


@with_login
def query(q):
    return client.query(q)


def read_values(f, properties):
    output = []
    for line in f.readlines():
        values = line.split()
        if len(values) < 1:
            continue
        d = dict()

        for n, name in enumerate(properties):
            if n < len(values):
                d[name] = values[n]
            else:
                d[name] = None
        output.append(d)
    return output


"""Initializes packages, s3 buckets, etc for this session"""
# Registering buckets
with open(os.path.join('raw_ini', 'buckets.txt')) as f:
    buckets = client.buckets_list()
    config = read_values(f, ["name", "region", "access_key", "secret_key"])
    for b in config:
        if b["name"] not in buckets:
            app.logger.info('Registering bucket s3://%s' % b["name"])
            client.buckets_register(b["name"], b["region"], b["access_key"], b["secret_key"])

try:
    with open(os.path.join('raw_ini', 'rdbms.txt')) as f:
        servers = client.rdbms_list()
        config = read_values(f, ["name", "type", "host", "port", "db", "user", "passwd"])
        for s in config:
            if s["name"] not in servers:
                if s["type"] == "postgresql":
                    client.rdbms_register_postgresql(s["name"], s["host"], s["db"], int(s["port"]), s["user"],
                                                     s["passwd"])
                elif s["type"] == "sqlserver":
                    client.rdbms_register_sqlserver(s["name"], s["host"], s["db"], int(s["port"]), s["user"],
                                                    s["passwd"])
                elif s["type"] == "oracle":
                    client.rdbms_register_oracle(s["name"], s["host"], s["db"], int(s["port"]), s["user"], s["passwd"])
                elif s["type"] == "mysql":
                    client.rdbms_register_mysql(s["name"], s["host"], s["db"], int(s["port"]), s["user"], s["passwd"])
                else:
                    app.logger.error('unsupported database type %s, skipping' % s["type"])
except FileNotFoundError:
    app.logger.info("no file found with dbms servers")

views = client.views_list_names()
print(views)
# creating views
files = glob.glob(os.path.join('raw_ini', 'views/*.rql'))
files.sort()
for filename in files:
    # view filenames are prepended with a number '01_' which specifies the order for creating the view
    # so removing first 3 characters and last 4 (file extension)
    name = os.path.basename(filename)[3:-4]
    if name not in views:
        with open(filename) as f:
            app.logger.info('creating view %s' % name)
            client.views_create(name, f.read())

packages = client.packages_list_names()
# Registering packages
for filename in glob.glob(os.path.join('raw_ini', 'packages/*.rql')):
    name = os.path.basename(filename[:-4])
    if name not in packages:
        with open(filename) as f:
            app.logger.info('registering package %s' % name)
            client.packages_create(name, f.read())


# ----------------------------------------------------------------------------#
# Controllers.
# ----------------------------------------------------------------------------#
@app.context_processor
def inject_now():
    return {'now': datetime.datetime.now()}


@app.route('/')
def home():
    return redirect(url_for('machines'))


@app.route('/machines/list')
def machines_list():
    """List all available machines with main data"""
    data = query('''
        from machine_maintenance import machine_data, maint;
        
        select machineID as id,
                        model,
                        age,
                        lat,
                        long,
                        (select max(m.datetime) from maint m where m.machineID=machineID) as lmaint,
                        cast((select max(f.datetime) from failures f)  as date) as lfailure,
                        status
                    from machine_data''')
    # Adding url link for each machine
    l = []
    for m in data:
        m['url'] = url_for('single_machine', machine_id=m['id'])
        l.append(m)
    return jsonify(l)


@app.route('/machines/warnings')
def machines_warnings():
    """Service to get current warnings on machines."""
    results = query('''
        from machine_maintenance import machines;
        
        select machineID as id,
                    model,
                    age,
                    status
                from machines
                where status != "OK" ''')
    data = []
    for n, row in enumerate(results):
        timestamp = '2019-05-23 13:%d:00' % (10 * n)
        level = 'Error' if row['status'] == 'Failure' else 'Info'
        msg = 'machine %d in %s ' % (row['id'], row['status'])
        data.append(dict(machine_id=row['id'], timestamp=timestamp, level=level, msg=msg))
    # Adding fake warnings from the predictive maintenance algorithm
    data.append(dict(machine_id=5, timestamp='2019-05-23 13:45:00', level='Warning',
                     msg='Machine 5 with high probability of failing in the next 3 days'))
    data.append(dict(machine_id=45, timestamp='2019-05-23 13:45:00', level='Warning',
                     msg='Machine 45 with high probability of failing in the next 3 days'))
    return jsonify(data)


@app.route('/machines/report/failures_month')
def machines_failures_month():
    """Service just for plot 1 in main page"""
    results = query('''
        from machine_maintenance import failures, machines;
        
        select month,
                select count(*) from * p group by p.model model order by model
                from failures f, machines m
            where f.machineID = m.machineID and f.datetime > date "2015-01-01"
                group by month(f.datetime) month
                order by month''')
    return jsonify(list(results))


@app.route('/machines/report/errors_month')
def machines_errors_month():
    """Service just for plot 1 in main page"""
    results = query('''
        from machine_maintenance import errors, machines;
        
        select month,
                select count(*) from * p group by p.model model order by model
                from errors e, machines m
            where e.machineID = m.machineID and e.datetime > date "2015-01-01"
                group by month(e.datetime) month
                order by month''')
    return jsonify(list(results))


@app.route('/machines/report/failures_model')
def machines_failures_model():
    """Service just for plot 2 in main page"""
    results = query('''
        from machine_maintenance import failures, machines;
        
        select "machine " + mach as machine, count(*) N
                from failures f, machines m
            where f.machineID = m.machineID and f.datetime > date "2015-01-01"
                group by f.machineID mach
                order by N desc
            limit 20''')
    return jsonify(list(results))


features_dir = tempfile.TemporaryDirectory(prefix='raw-app-features')
logging.info("using %s as features folder" % features_dir.name)


@app.route('/machines/create_features', methods=['POST'])
def machines_create_features():
    """Creates features for predictive maintenance training"""
    data = request.json
    q = query('''
        from machine_maintenance import features;
        
        select f.features, if (f.failure = 0) then 0 else 1 as failure
        from features(interval "{0} days", interval "{1} days", date "{2}", date "{3}") f '''
              .format(data['measureDays'], data['predictionDays'], data['start'], data['end']))
    features = list(q)
    failures = 0
    good = 0
    for f in features:
        if f['failure'] == 0:
            good += 1
        else:
            failures += 1

    name = str(uuid.uuid1())

    with open(os.path.join(features_dir.name, name), mode='w') as f:
        json.dump(features, f)
    return jsonify(dict(name=name, failures=failures, good=good))


@app.route('/machines/model_train', methods=['POST'])
def machines_model_train():
    """Trains classifier and returns json with results"""
    data = request.json
    with open(os.path.join(features_dir.name, data['name'])) as f:
        features = json.load(f)
    results = prediction_models.machines_train(features, data['classifier'], data['train_test'], data['good_bad'])
    return jsonify(results)


@app.route('/machines')
def machines():
    return render_template('pages/machines.html')


@app.route('/machines/train')
def machines_train():
    return render_template('pages/machines_train.html')


@app.route('/machines/<int:machine_id>/status/')
def machine_status(machine_id):
    """Service for individual machine status"""
    results = query('''
        from machine_maintenance import machine_data, maint;

         select lat, long, model, age, status,
                   (select max(l.datetime) from maint l where l.machineID = {0}) as last_maint,
                   (select l.datetime, l.failure from failures l order by l.datetime desc limit 5) as last_failures
           from  machine_data
           where machineID = {0}'''.format(machine_id))

    return jsonify(results.next())


@app.route('/machines/<int:machine_id>/telemetry/')
def machine_telemetry(machine_id):
    """Service for individual machine telemetry reading
        needs url encoded arguments for start and end of measurements"""
    start = request.args.get('start')
    end = request.args.get('end')
    results = query('''
         from machine_maintenance import machine_data;
         start := date "%s";
         end := date "%s";
         
         select
             select t.datetime, t.volt, t.rotate, t.pressure, t.vibration  from telemetry t where t.datetime >= start and t.datetime <= end order by t.datetime asc as telemetry,
             select t.datetime, t.error from errors t where t.datetime >= start and t.datetime <= end order by t.datetime asc as errors,
             select t.datetime, t.failure from failures t where t.datetime >= start and t.datetime <= end order by t.datetime asc as failures
         from  machine_data
               where machineID = %d''' % (start, end, machine_id))

    return jsonify(results.next())


@app.route('/machines/<int:machine_id>')
def single_machine(machine_id):
    return render_template('pages/single_machine.html', machine_id=machine_id)


# Error handlers.


@app.errorhandler(500)
def internal_error(error):
    # db_session.rollback()
    return render_template('errors/500.html'), 500


@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404


if not app.debug:
    file_handler = FileHandler('error.log')
    file_handler.setFormatter(
        Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
    )
    app.logger.setLevel(logging.INFO)
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.info('errors')

# ----------------------------------------------------------------------------#
# Launch.
# ----------------------------------------------------------------------------#

# Default port:
if __name__ == '__main__':
    app.run()

# Or specify port manually:
'''
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
'''
