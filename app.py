# ----------------------------------------------------------------------------#
# Imports
# ----------------------------------------------------------------------------#

import datetime
import glob

import os
from functools import wraps

from logging import Formatter, FileHandler
from flask import Flask, render_template, request, jsonify, url_for, session, redirect
from authlib.flask.client import OAuth
from six.moves.urllib.parse import urlencode

from rawapi import new_raw_client
import logging
import json
import uuid
import tempfile

import prediction_models

# ----------------------------------------------------------------------------#
# App Config.
# ----------------------------------------------------------------------------#

app = Flask(__name__)
app.config.from_object('config')

logging.basicConfig(
    level='INFO'
)


def create_client():
    return new_raw_client()


def init_packages():
    client = create_client()
    # Registering buckets
    with open(os.path.join('raw_ini', 'buckets.txt')) as f:
        buckets = client.buckets_list()
        for line in f.readlines():
            values = line.split()
            if len(values) < 1:
                continue

            name = values[0]
            region = values[1] if len(values) >= 2 else None
            access_key = values[2] if len(values) >= 3 else None
            secret_key = values[3] if len(values) >= 4 else None

            if name not in buckets:
                app.logger.info('Registering bucket s3://%s' % name)
                client.buckets_register(name, region, access_key, secret_key)

    packages = client.packages_list_names()
    # Registering packages
    for filename in glob.glob(os.path.join('raw_ini', 'packages/*.rql')):
        name = os.path.basename(filename[:-4])
        if name in packages:
            app.logger.warning('overwriting package %s' % name)
            client.packages_drop(name)
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
    client = create_client()
    data = client.query('''
        from machine_maintenance import machine_data, maint;
        
        select machineID as id,
                        model,
                        age,
                        lat,
                        long,
                        cast((select max(m.datetime) from maint m where m.machineID=machineID) as date ) as lmaint,
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
    client = create_client()
    results = client.query('''
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
        msg = 'machine %d in status %s ' % (row['id'], row['status'])
        data.append(dict(machine_if=row['id'], timestamp=timestamp, level=level, msg=msg))
    # Adding fake warnings from the predictive maintenance algorithm
    data.append(dict(machine_id=5, timestamp='2019-05-23 13:45:00', level='Warning',
                     msg='Machine 5 with high probability of failing in the next 3 days'))
    data.append(dict(machine_id=45, timestamp='2019-05-23 13:45:00', level='Warning',
                     msg='Machine 45 with high probability of failing in the next 3 days'))
    return jsonify(data)


@app.route('/machines/report/failures_month')
def machines_failures_month():
    """Service just for plot 1 in main page"""
    client = create_client()
    results = client.query('''
        from machine_maintenance import failures, machines;
        
        select month,
                select count(*) from * p group by p.model model order by model
                from failures f, machines m
            where f.machineID = m.machineID and f.datetime > date "2015-01-01"
                group by month(f.datetime) month
                order by month''')
    return jsonify(list(results))


@app.route('/machines/report/failures_model')
def machines_failures_model():
    """Service just for plot 2 in main page"""
    client = create_client()
    results = client.query('''
        from machine_maintenance import failures, machines;
        
        select "machine " + mach as machine, count(*) N
                from failures f, machines m
            where f.machineID = m.machineID and f.datetime > date "2015-01-01"
                group by f.machineID mach
                order by N desc
            limit 10''')
    return jsonify(list(results))


features_dir = tempfile.TemporaryDirectory(prefix='raw-app-features')
logging.info("using %s as features folder" % features_dir.name)


@app.route('/machines/create_features', methods=['POST'])
def machines_create_features():
    """Creates features for predictive maintenance training"""
    data = request.json
    client = create_client()
    q = client.query('''
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
    client = create_client()
    results = client.query('''
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
    client = create_client()
    start = request.args.get('start')
    end = request.args.get('end')
    results = client.query('''
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
    init_packages()
    app.run()

# Or specify port manually:
'''
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
'''
