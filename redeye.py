from re import M
import eventlet
eventlet.monkey_patch()
from flask import Flask, request, render_template, session, request, redirect, abort, make_response, url_for, send_from_directory, flash, jsonify, Markup
from flask_jsglue import JSGlue
import jwt
import sqlite3
from os import walk, path, listdir, sep, makedirs, remove
import os
from RedDB import db
from Parse import Parse as parse
from Report import report_gen as report
import Redhelper as helper
import collections
from werkzeug.utils import secure_filename
import csv
from datetime import datetime, timedelta
from uuid import uuid4
import base64
import json
from collections import defaultdict
import urllib.parse
from flask_socketio import SocketIO, emit
import socketio as client_socket
from threading import Thread, Lock
from urllib.parse import unquote
from shutil import copy as copyFile


app = Flask(__name__, template_folder="templates")
jsglue = JSGlue(app)
socketio = SocketIO(app, cors_allowed_origins="http://localhost")

# Connect to redeye
sio = client_socket.Client()

app.config['SESSION_COOKIE_NAME'] = "RedSession"
app.secret_key = str(uuid4())  # Nice

clients = {} #key: username; value: list of sockets
#/SocketIO
connected_hosts = {} # key: host_id. value: last time asked for actions.
thread = None
thread_lock = Lock()

# login page with projects.
projects = []

# CONSTS
IS_ENV_SAFE = True # If enviroment is exposed to network (redeye should be less permissive) set this to False.
PROFILE_PICS = r"static/pics/profiles"
DEFAULT_JSONS = r"static/jsons"
DEFAULT_DB = r"ExampleDB"
PRIVATE_MESSAGE = 1
GROUP_MESSAGE = 2
GLOBAL_MESSAGE = 3
APP = "red"
#Init
def init(app):
    global projects
    projects = db.get_projects()
    print(projects)
    for project in projects:
        d1,d2,d3,d4,d5,d6,d7,d8,d9 = helper.setFilesFolder(project[2])
        makedirs(d1, exist_ok=True)
        makedirs(d2, exist_ok=True)
        makedirs(d3, exist_ok=True)
        makedirs(d4, exist_ok=True)
        makedirs(d5, exist_ok=True)
        makedirs(d6, exist_ok=True)
        makedirs(d7, exist_ok=True)
        makedirs(d8, exist_ok=True)
        makedirs(d9, exist_ok=True)
        makedirs("files", exist_ok=True)

"""
=======================================================
                Servers Functions
=======================================================
"""

@app.route('/server', methods=['GET'])
def server():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if not request.method == 'GET':
        abort(404)

    if request.values.get('ip'):
        server_ip = request.values.get('ip')
        server = db.get_server_by_ip(session["db"], server_ip)

    elif request.values.get('id'):
        server_id = request.values.get('id')
        server = db.get_server_by_id(session["db"], server_id)

    if server:
        server = server[0]
    else:
        abort(404)

    users = db.get_users_by_server_id(session["db"], server[0])
    vulns = db.get_vulns_by_server_id(session["db"], server[0])
    files = db.get_files_by_server_id(session["db"], server[0])
    ports = db.get_ports_by_server_id(session["db"], server[0])
    attain = db.get_attain_by_server_id(session["db"], server[0])[0][0]
    vendor = db.get_vendor_by_server_id(session["db"], server[0])[0][0]
    users_with_type = []
    for user in users:
        type = helper.user_type_to_name(user[1])
        tuser = [user[0], type, user[2], user[3], user[4], user[5], user[6], user[7], user[8], user[9], user[10]]
        users_with_type.append(tuser)
    return render_template('server.html', project=session["project"], username=session["username"], server=server, users=users_with_type, vulns=vulns, files=files, ports=ports, attain=attain, vendor=vendor)

@app.route('/edit_server', methods=['GET'])
def edit_server():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'GET':
        server_ip = request.values.get('ip')
        section = request.values.get('section')
        server = db.get_server_by_ip(session["db"], server_ip)
        sections = db.get_sections(session["db"])
        if not section:
            for sec in sections:
                if sec[0] == server[0][7]:
                    section = sec[1]
        if server:
            server = server[0]
            users = db.get_users_by_server_id(session["db"], server[0])
            vulns = db.get_vulns_by_server_id(session["db"], server[0])
            files = db.get_files_by_server_id(session["db"], server[0])
            ports = db.get_ports_by_server_id(session["db"], server[0])
            attain = db.get_attain_by_server_id(session["db"], server[0])[0][0]
            return render_template('edit_server.html', project=session["project"], username=session["username"], sections=sections, section=section, server=server, users=users, vulns=vulns, files=files, ports=ports, attain=attain)
    return render_template('edit_server.html', project=session["project"], username=session["username"], sections=sections, section=section, server=["", "", ""], users=[], vulns=[])

@app.route('/servers')
def servers():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    dbsections = db.get_sections(session["db"])
    allData = {}
    for section in dbsections:
        sectionId = section[0]
        name = section[1]
        servers = db.get_servers_by_section_id(session["db"], sectionId)
        serverData = {}
        for server in servers:
            ports = db.get_ports_by_server_id(session["db"], server[0])
            users = db.get_users_by_server_id(session["db"], server[0])
            serverData[server[0]] = { 'srvDetails':server,'ports':ports, 'users':users }
        allData[sectionId] = {'name': name,'info': serverData} 

    # {'SectionId': {
    #   servers : {id:{'server':(tuple),'ports':[ports],'users':[users]},..,}
    # , "SectionName2"...}
    return render_template('servers.html', project=session["project"], username=session["username"], data=allData)

@app.route('/update_server_attain', methods=['POST'])
def update_server_attain():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'POST':
        id = request.form.get('id')
        attain = request.form.get('attain')
        db.update_server_details(session["db"], session["username"], id, attain=attain)
        return ('', 204)

@app.route('/delete_server', methods=['POST'])
def delete_server():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'POST':
        id = request.form.get('id')
        db.delete_server_by_id(session["db"], id, session["username"])
        return redirect('servers')

@app.route('/change_server', methods=['POST'])
def change_server():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'POST':
        name = request.form.get('name')
        ip = request.form.get('ip')
        id = request.form.get('id')
        attain = request.form.get('attain')
        section_id = request.form.get('section')
        access = 1 if request.form.get('access') else 0
        if id:
            db.update_server_details(
                session["db"], session["username"], id, ip=ip, name=name, is_access=access, attain=attain, section_id=section_id)
        else:
            db.create_new_server(session["db"], session["username"],
                                 ip, name, "", access, attain, section_id)
        return redirect(url_for('server') + '?ip=' + ip)
    
@app.route('/add_server_from_file', methods=['POST'])
def add_server_from_file():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)
    if request.method == 'POST':
        files = request.files.getlist("upload_file")
        for file in files:
            add_scan(file)

    return redirect('servers')


@app.route('/change_section_name', methods=['POST'])
def change_section_name():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    dict = request.args.to_dict()
    db.change_section_id(session["db"], dict['id'], dict['newName'])
    return redirect('servers')


@app.route('/add_new_section', methods=['POST'])
def add_new_section():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    db.create_new_server_section(session["db"],"NewSection")
    return redirect('servers')

"""
=======================================================
                Logs Functions
=======================================================
"""

@app.route('/logs',methods=['GET','POST'])
def logs():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    logs = db.get_all_log(session["db"])
    if request.method == 'POST':
        keyword = request.form.get('key_word')
        if keyword != '' and keyword is not None:
            all_objects,logs,days,month_years = helper.get_logs(session["db"], logs,keyword)
        else:
            all_objects,logs,days,month_years = helper.get_logs(session["db"], logs)

    else:
        all_objects,logs,days,month_years = helper.get_logs(session["db"], logs)
    return render_template('logs.html', project=session["project"], username=session["username"], objects=all_objects, log=logs, len=len(all_objects), day=days, year=month_years)

@app.route('/logs2',methods=['GET','POST'])
def logs2():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    logs = db.get_all_log(session["db"])
    if request.method == 'POST':
        keyword = request.form.get('key_word')
        if keyword != '' and keyword is not None:
            all_objects,logs,days,month_years = helper.get_logs(session["db"], logs,keyword)
        else:
            all_objects,logs,days,month_years = helper.get_logs(session["db"], logs)

    else:
        all_objects,logs,days,month_years = helper.get_logs(session["db"], logs)

    return render_template('logs2.html', project=session["project"], username=session["username"], objects=all_objects, log=logs, len=len(all_objects), day=days, year=month_years)

@app.route('/export_logs', methods=['POST'])
def export_logs():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    objects = request.form.get('objects').split(r"[")
    logs = request.form.get('logs').split(r"(")

    with open(os.path.join(helper.FILES_FOLDER.format(session["project"]), "logs.csv"), 'w', newline='') as csv_file:
        fieldnames = ['Log Name', 'Details', "Date", "Time"]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)

        for objs, log in zip(objects[2:], logs[1:]):
            objs, log = objs.split(r","), log.split(r",")

            if log[7] == "User Created":
                details = objs[3][2:-1]
            else:
                details = objs[2][2:-1]

            log_name, date, time = log[7][2:-1], log[8][2:-1], log[9][2:-1]
            writer.writerow(
                {'Log Name': log_name, 'Details': details, 'Date': date, 'Time': time})

    return send_from_directory(helper.FILES_FOLDER.format(session["project"]), "logs.csv", as_attachment=True)

"""
=======================================================
                Tasks Functions
=======================================================
"""

@app.route('/tasks')
def tasks():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    tasks = db.get_all_tasks(session["db"])

    my_tasks = db.get_all_my_tasks(session["db"], session["username"])
    my_tasks_lst = []
    for task in my_tasks:
        t = list(task)
        if t[5] is not None:
            if "\r\n" in t[5]:
                t[5] = t[5].replace('\r\n', " ")
        my_tasks_lst.append(t)

    team_members = db.get_redeye_users_names()
    return render_template('tasks.html', project=session["project"], username=session["username"], all_tasks=tasks, len=len(tasks), my_tasks=my_tasks_lst, my_tasks_len=len(my_tasks_lst), team_members=team_members, len_members=len(team_members))

@app.route('/edit_note', methods=['POST'])
def edit_note():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    note_dic = {}
    for key, val in request.form.items():
        note_dic[key] = val
    if "id" not in note_dic:
        return redirect(url_for('tasks'))
    else:
        if 'taskname' in note_dic:
            db.edit_name_for_task(session["db"], note_dic['taskname'],note_dic["id"])
        if 'data' in note_dic:
            db.edit_data_for_task(session["db"], note_dic['data'],note_dic["id"])
        if 'attain' in note_dic:
            db.add_note_for_task(session["db"], note_dic['attain'],note_dic["id"])
        if 'exec' in note_dic:
            if db.is_task_private(session["db"], note_dic["id"])[0]:
                db.change_task_privacy(session["db"], note_dic["id"])
            db.edit_exec_for_task(session["db"], note_dic["exec"], note_dic["id"])

    return redirect(url_for('tasks'))

@app.route('/add_task', methods=['POST'])
def add_task():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)
    if request.method == 'POST':
        task = {}
        new_task = request.form.items()
        for key, value in new_task:
            task[key] = value

        if task['task_data'] == '':
            task['task_data'] = task['task_name']
        
        task = helper.set_task(task)
        try:
            db.insert_new_task(session["db"], task['task_name'], 0, task['task_executer'], task['task_data'], int(
                task['private']), session["username"])
        except Exception:
            return redirect(url_for('tasks'))
        finally:
            return redirect(url_for('tasks'))

@app.route('/update_task', methods=['POST'])
def update_task():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)
    if request.method == 'POST':
        task = {}
        task_items = request.form.items()
        for key, value in task_items:
            task[key] = value
        if 'task_done' in task:
            db.delete_task(session["db"], task['task_id'], session["username"])
        elif 'trash_task' in task:
            db.unrelevent_task(session["db"], task['task_id'], session["username"])
        else:
            pass
        return redirect(url_for('tasks'))

"""
=======================================================
                Users Functions
=======================================================
"""

@app.route('/create_user', methods=['POST'])
def create_user():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'POST':
        user_name = request.form.get('username')
        user_pass = request.form.get('password')
        user_perm = request.form.get('permissions')
        user_type = request.form.get('type')
        server_id = request.form.get('server_id')
        server_ip = request.form.get('server_ip')
        
        if not user_name:
            return redirect(request.referrer)
        if not user_pass:
            user_pass = "Unknown"
        if not user_perm:
            user_perm = "READ | WRITE"
        if not user_type or int(user_type) == 6:
            manual_type = request.form.get('select_type')
            if manual_type:
                user_type = helper.user_name_to_type(manual_type)
            else:
                user_type = 5
        found = "NULL"
        if not server_id:
            found = request.form.get('found')
            if db.get_server_id_by_name(session["db"], found) or db.get_server_id_by_ip(session["db"], found):
                if db.get_server_id_by_name(session["db"], found):
                    server_id = db.get_server_id_by_name(session["db"], found)[0][0]
                else:
                    server_id = db.get_server_id_by_ip(session["db"], found)[0][0]
                found = "NULL"
            else:
                server_id = "NULL"

        db.insert_new_user(session["db"], user_type,server_id, found, user_name, user_pass,
                                user_perm, session["username"])
        return redirect(request.referrer)

@app.route('/edit_user', methods=['POST'])
def edit_user():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'POST':
        url = request.form.get('refferer')
        user_id = request.form.get('id')
        if not user_id:
            return render_template('404.html'), 404
        user_name = request.form.get('username')
        user_pass = request.form.get('password')
        user_perm = request.form.get('permissions')
        user_type = request.form.get('type')
        user_found_on = request.form.get('found')
        user_attain = request.form.get('attain')

        """ User can be found on one server but be relevant to another.
        if db.get_server_id_by_name(session["db"], user_found_on) or db.get_server_id_by_ip(session["db"], user_found_on):
            if db.get_server_id_by_name(session["db"], user_found_on):
                server_id = db.get_server_id_by_name(session["db"], user_found_on)[0][0]
            else:
                server_id = db.get_server_id_by_ip(session["db"], user_found_on)[0][0]
        else:
            server_id = ""
        """
        db.edit_user(session["db"], session["username"], user_id, name=user_name,
                     passwd=user_pass, perm=user_perm, type=user_type, found_on=user_found_on, found_on_server=False, attain=user_attain)
        if 'userid' in url:
            url = url.split('userid=')
            url = url[0] + 'userid=' + user_id
        else:
            url = url + \
                ('?userid=' if '?' not in url else '&userid=') + user_id
        return redirect(url)

@app.route('/delete_user')
def delete_user():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'GET':
        user_id = request.values.get('id')
        db.delete_user(session["db"], user_id, session["username"])
        return ('', 204)

@app.route('/domain_users', methods=['GET'])
def domain_users():
    data = collections.defaultdict(list)
    users = db.get_all_domain_users(session["db"])
    for user in users:
        u_type, username, password, perm, attain, uid = user[
            1], user[2], user[3], user[4], user[5], user[0]
        server_name = helper.set_user_server_name(session["db"], user[7],user[8])

        data[username].append(
            [password, perm, server_name, u_type, attain, uid])

    return render_template('users.html', project=session["project"], username=session["username"], data=data, type=1)

@app.route('/localhost_users', methods=['GET'])
def localhost_users():
    data = collections.defaultdict(list)
    users = db.get_all_localhost_users(session["db"])
    for user in users:
        u_type, username, password, perm, attain, uid = user[
            1], user[2], user[3], user[4], user[5], user[0]
        server_name = helper.set_user_server_name(session["db"], user[7],user[8])

        data[username].append(
            [password, perm, server_name, u_type, attain, uid])

    return render_template('users.html', project=session["project"], username=session["username"], data=data, type=2)

@app.route('/application_users', methods=['GET'])
def application_users():
    data = collections.defaultdict(list)
    users = db.get_all_application_users(session["db"])
    for user in users:
        u_type, username, password, perm, attain, uid = user[
            1], user[2], user[3], user[4], user[5], user[0]
        server_name = helper.set_user_server_name(session["db"], user[7],user[8])

        data[username].append(
            [password, perm, server_name, u_type, attain, uid])

    return render_template('users.html', project=session["project"], username=session["username"], data=data, type=3)

@app.route('/netdevice_users', methods=['GET'])
def netdevice_users():
    data = collections.defaultdict(list)
    users = db.get_all_netdevices_users(session["db"])
    for user in users:
        u_type, username, password, perm, attain, uid = user[
            1], user[2], user[3], user[4], user[5], user[0]
        device_ip = helper.set_user_device_name(session["db"], user[7],user[9])

        data[username].append([password, perm, device_ip, u_type, attain, uid])
    return render_template('users.html', project=session["project"], username=session["username"], data=data, type=4)

@app.route('/other_users', methods=['GET'])
def other_users():
    data = collections.defaultdict(list)
    users = db.get_all_other_users(session["db"])
    for user in users:
        u_type, username, password, perm, attain, uid, info = user[
            1], user[2], user[3], user[4], user[5], user[0], user[10]
        
        info = helper.set_user_other_user(session["db"], user[7],info)
        data[username].append([password, perm, info, u_type, attain, uid])

    return render_template('users.html', project=session["project"], username=session["username"], data=data, type=5)

@app.route('/all_users', methods=['GET'])
def all_users():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    data = collections.defaultdict(list)
    users = db.get_all_users(session["db"])
    for user in users:
        u_type, username, password, perm, attain, uid = user[
            1], user[2], user[3], user[4], user[5], user[0]
        if user[8] is not None:
            info = helper.set_user_server_name(session["db"], user[7],user[8])
        elif user[9] is not None:
            info = helper.set_user_device_name(session["db"], user[7],user[9])
        elif user[10] is not None:
            info = helper.set_user_other_user(session["db"], user[7],info)
        elif user[7] is not None:
            info = user[7]
        else:
            info = "Unknown"
        u_type = helper.user_type_to_name(u_type)
        data[username].append([password, perm, info, u_type, attain, uid])

    return render_template('users.html', project=session["project"], username=session["username"], data=data, type=6)

@app.route('/export_users', methods=['POST'])
def export_users():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    users = db.get_users(session["db"])

    with open(os.path.join(helper.FILES_FOLDER.format(session["project"]), "users.csv"), 'w', newline='') as csv_file:
        fieldnames = ['Username', 'Password', 'Permission', "Type", "Attain"]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)

        writer.writeheader()
        for user in users:
            user_name, password, perm, user_type, attain = user[2], user[3], user[4], user[1], user[5]
            user_type = helper.user_type_to_name(user_type)
            writer.writerow({'Username': user_name, 'Password': password,
                             'Permission': perm, 'Type': user_type, 'Attain': attain})
    return send_from_directory(helper.FILES_FOLDER.format(session["project"]), "users.csv", as_attachment=True)

@app.route('/add_users_from_file', methods=['POST'])
def add_users_from_file():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'POST':
        files = request.files.getlist("upload_file")

        for file in files:
            full_path, file_name = helper.save_file(file, helper.PASS_FOLDER.format(session["project"]))
            if file_name:
                parse.parse_users_passwords(
                    session["username"], file_name, full_path)

    return redirect(request.referrer)

"""
=======================================================
                Vulns Functions
=======================================================
"""

@app.route('/create_vuln', methods=['POST'])
def create_vuln():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'POST':
        name = request.form.get('name')
        desc = request.form.get('description')
        fix = request.form.get('fix')
        server_id = request.form.get('server_id')
        server_ip = request.form.get('server_ip')
        if not name:
            return redirect(url_for('edit_server') + '?ip=' + server_ip)
        if not desc:
            desc = '-'
        if not fix:
            fix = '-'
        db.insert_new_vuln(session["db"], name, desc, fix, server_id,
                           session["username"])
        return redirect(url_for('edit_server') + '?ip=' + server_ip)

@app.route('/delete_vuln')
def delete_vuln():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'GET':
        vuln_id = request.values.get('id')
        db.delete_vuln(session["db"], vuln_id, session["username"])
        return ('', 204)

"""
=======================================================
                Comments Functions
=======================================================
"""

@app.route('/delete_comment', methods=['POST'])
def delete_comment():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'POST':
        comment_id = request.form.get('id')
        db.delete_comment_by_id(session["db"], comment_id)
        return redirect(url_for('index'))


@app.route('/create_comment', methods=['POST'])
def create_comment():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'POST':
        data = request.form.get('data')
        db.create_comment(session["db"], data, session["username"])
        return redirect(url_for('index'))

"""
=======================================================
                Ports Functions
=======================================================
"""
@app.route('/delete_port')
def delete_port():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'GET':
        port_id = request.values.get('id')
        db.delete_port_by_id(session["db"], port_id)

    return redirect(request.referrer)


@app.route('/create_server_port', methods=['POST'])
def create_server_port():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    port_dict = {}
    for key, val in request.form.items():
        port_dict[key] = val

    if port_dict["service"]== "":
        port_dict["service"] = helper.get_service_name_by_port(port_dict["port"])
    
    if port_dict["state"]== "":
        port_dict["state"] = "open"

    db.insert_new_port(session["db"], port_dict["port"], port_dict["state"], port_dict["service"],
                       port_dict["vuln"], "server_id", port_dict["server_id"])

    return redirect(request.referrer)

"""
=======================================================
                Files Functions
=======================================================
"""
@app.route('/delete_file')
def delete_file():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'GET':
        file_id = request.values.get('id')
        db.delete_file(session["db"], file_id, session["username"])
        return ('', 204)

@app.route('/delete_file_from_dir')
def delete_file_from_dir():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)
    path = request.args.get("path")
    helper.delete_file(path)
    return redirect(request.referrer)

@app.route('/upload_file', methods=['POST'])
def upload_file():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'POST':
        files = request.files.getlist("upload_file")
        try:
            current_dir = request.referrer.split('dir_name=')[1]
            # url decoding the string.
            current_dir = urllib.parse.unquote(current_dir)
            if helper.secure_file_name(current_dir):
                return render_template('404.html'), 404
        except Exception:
            current_dir = helper.FILES_FOLDER.format(session["project"])

        if "edit_server" in request.referrer:
            server_id = db.get_server_id_by_ip(session["db"], 
                (request.referrer).split(r"=")[-1])[0][0]

        for file in files:
            # Problem with secure_filename - not supporting hebrew
            #file_name = secure_filename(file.filename)
            full_path, file_name = helper.save_file(file, current_dir)
            if file_name:
                try:
                    db.insert_new_file(session["db"], full_path, file_name, "Added from {} file".format(
                        file_name), server_id, session["username"])
                except Exception:
                    db.insert_new_standalone_file(session["db"], full_path, file_name, "Added from {} file".format(
                        file_name), session["username"])
            else:
                pass

    return redirect(request.referrer)


@app.route('/files/', methods=['GET', 'POST'])
def files():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)
    if request.method == 'GET':
        file_path = request.args.get('file_name')
        if not file_path:
            return render_template('404.html'), 404
        # Jinja will return a list in str format
        if file_path[-1] == "]":
            file_path = file_path[2:-2]

        path, name = file_path.rsplit("/", 1)
        if helper.secure_file_name(file_path):
            return render_template('404.html'), 404
        else:
            if "load_files" in request.referrer:
                return send_from_directory(os.path.abspath(path), name)
            else:
                return send_from_directory(os.path.abspath(path), name,as_attachment=True)
    else:
        return render_template('404.html'), 404

@app.route('/delete_files', methods=['GET'])
def delete_files():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    file_path = request.args.get('file_path')

    helper.delete_file(file_path)
    return redirect(request.referrer)

@app.route('/load_files', methods=['GET', 'POST'])
def load_files():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)
    current_dir = request.args.get("dir_name")

    if not current_dir:
        full_path = helper.MAIN_FILES.format(session["project"])

    else:
        if helper.secure_file_name(current_dir):
            return render_template('404.html'), 404 
        else:
            full_path = current_dir
    
    if request.method == 'POST':
        key_word = {}
        objects = request.form.items()
        for key, val in objects:
            key_word[key] = val
        if key_word['key_word'] != '' and key_word['key_word'] is not None:
            # User Entered a Key word
            keyword_files = defaultdict(list)
            for key,val in helper.get_all_files(helper.MAIN_FILES.format(session["project"])).items():
                if key_word['key_word'].lower() in key.lower():
                    keyword_files[key].append(val)
    
            if keyword_files:
                return render_template('load_files.html', project=session["project"], username=session["username"],root="Found files for {}".format(key_word['key_word']),dirs={},files=keyword_files, files_found=len(keyword_files))

            else:
                root, dirs, files,last_dir = helper.share_files(full_path)
                return render_template('load_files.html', project=session["project"], username=session["username"], root=root, dirs=dirs, files=files,files_found="0",last_dir=last_dir)
        else:
            root, dirs, files,last_dir = helper.share_files(full_path)
            return render_template('load_files.html', project=session["project"], username=session["username"], root=root, dirs=dirs, files=files,files_found="None",last_dir=last_dir)    
    else:
        root, dirs, files,last_dir = helper.share_files(full_path)
        return render_template('load_files.html', project=session["project"], username=session["username"], root=root, dirs=dirs, files=files,files_found="None",last_dir=last_dir)

@app.route('/add_new_dir', methods=['POST'])
def add_new_dir():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    current_dir = request.referrer.split('dir_name=')[1]
    # url decoding the string.
    full_path = urllib.parse.unquote(current_dir)
    dir_name = request.form.get('dir_name')
    if helper.secure_file_name(full_path) or helper.secure_file_name(dir_name):
        return render_template('404.html'), 404
    else:
        os.mkdir(os.path.join(full_path,dir_name))
    return redirect(request.referrer)

"""
=======================================================
                Stats Functions
=======================================================
"""

@app.route('/stats', methods=['GET'])
def stats():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    servers = db.get_servers(session["db"])
    no_access_servers = db.get_no_access_servers(session["db"])
    users = db.get_users(session["db"])
    cracked_users = db.get_all_cracked_users(session["db"])
    netdevices = db.get_all_netdevices(session["db"])
    vullns = db.get_all_vullns(session["db"])
    achievements = db.get_achievements(session["db"])
    days, time = helper.time_left()

    return render_template('stats.html', project=session["project"], username=session["username"], servers_len=len(servers),no_access_len=len(no_access_servers), users_len=len(users), netdevices_len=len(netdevices), vullns_len=len(vullns), cracked_users_len=len(cracked_users), achievements=achievements, achievements_len=len(achievements), time_left=time, days=days)

"""
=======================================================
                Attacks Functions
=======================================================
"""

@app.route('/new_attack')
def new_attack():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    name = "New"
    jfiles = os.listdir(helper.JSON_FOLDER.format(session["project"]))

    for i in range(1, len(jfiles) + 1):
        if f"{name}{str(i)}.json" not in jfiles:
            name += str(i)
            name += ".json"
            break

    with open(os.path.join(helper.JSON_FOLDER.format(session["project"]), name), 'w', newline='') as data:
        data.write('{"operators":{},"links":{},"operatorTypes":{},"severity":"1","plausibility":"1","risk":"1"}')
    
    dic_data = {}
    attacks = os.listdir(helper.JSON_FOLDER.format(session["project"]))
    attacks.remove("New")
    for i, attack in enumerate(attacks):
        attacks[i] = attack[:-5]
        with open(os.path.join(helper.JSON_FOLDER.format(session["project"]), attack), 'r', newline='') as data:
            dic_data[attack] = data.read()
    
    return render_template('attack.html', project=session["project"], username=session["username"], attacks=attacks, attacks_len=len(attacks), data=dic_data, tab=name)


@app.route('/attack', methods=['GET', 'POST'])
def attack():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    tab = ""

    if request.method == 'POST':
        original_name = request.form.get('current-attack-name')
        name = request.form.get('attack-name')
        last_name = request.form.get('last-attack-name')
        tab = request.form.get('tab')
        jdata = request.form.get('json')

        if name != last_name:
            if last_name + ".json" in os.listdir(helper.JSON_FOLDER.format(session["project"])):
                os.remove(os.path.join(helper.JSON_FOLDER.format(session["project"]),last_name + ".json"))

        with open(os.path.join(helper.JSON_FOLDER.format(session["project"]), r"{}.json".format(name)), 'w', newline='') as data:
            data.write(jdata)
        if original_name != name:
            if original_name in os.listdir(helper.JSON_FOLDER.format(session["project"])):
                os.remove(os.path.join(helper.JSON_FOLDER.format(session["project"]), r"{}.json".format(original_name)))
    
    dic_data = {}
    if session["project"] == DEFAULT_DB:
        copyFile(DEFAULT_JSONS + "/Attack.json", helper.JSON_FOLDER.format(session["project"]))

    attacks = os.listdir(helper.JSON_FOLDER.format(session["project"]))
    if "New" in attacks:
        attacks.remove("New")
    for i, attack in enumerate(attacks):
        attacks[i] = attack[:-5]
        with open(os.path.join(helper.JSON_FOLDER.format(session["project"]), attack), 'r', newline='') as data:
            dic_data[attack] = data.read()
        

    return render_template('attack.html', project=session["project"], username=session["username"], attacks=attacks, attacks_len=len(attacks), data=dic_data, tab=tab)


@app.route('/delete_attack')
def delete_attack():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'GET':
        attack_name = request.values.get('name')
        attack_name += ".json"
        if attack_name in os.listdir(helper.JSON_FOLDER.format(session["project"])):
            os.remove(os.path.join(helper.JSON_FOLDER.format(session["project"]),attack_name))
    
    dic_data = {}
    attacks = os.listdir(helper.JSON_FOLDER.format(session["project"]))
    attacks.remove("New")
    for i, attack in enumerate(attacks):
        attacks[i] = attack[:-5]
        with open(os.path.join(helper.JSON_FOLDER.format(session["project"]), attack), 'r', newline='') as data:
            dic_data[attack] = data.read()    

    return render_template('attack.html', project=session["project"], username=session["username"], attacks=attacks, attacks_len=len(attacks), data=dic_data, tab="")

"""
=======================================================
                Report Functions
=======================================================
"""

@app.route('/build_report')
def build_report():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    return render_template('build_report.html', project=session["project"], username=session["username"])


@app.route('/pre_report')
def pre_report():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    images = []
    data = db.get_all_report_data(session["db"])
    for image in data:
        images.append(helper.get_image(image[4]))
    return render_template('pre_report.html', project=session["project"], username=session["username"], data=data, len=len(data), images=images)


@app.route('/add_report', methods=['POST'])
def add_report():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    dic = {}
    if request.method == 'POST':
        for key, val in request.form.items():
            dic[key] = val
    
    img_extension = helper.get_img_extension(dic['image_data'])
    img_path = helper.save_image(r"{}{}".format(str(uuid4()),img_extension), dic['image_data'])
    db.save_to_report(session["db"], dic['data'], dic['section_name'], img_path)
    return redirect(request.referrer)

@app.route('/delete_from_report', methods=['GET'])
def delete_from_report():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)
    
    image_id = request.args.get('image_id')
    db.change_relevent_to_zero(session["db"], "report",image_id)

    return redirect(request.referrer)

@app.route('/update_report', methods=['POST'])
def update_report():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    dic = {}
    if request.method == 'POST':
        for key, val in request.form.items():
            dic[key] = val
    
    img_extension = helper.get_img_extension(dic['image_data'])
    img_path = helper.save_image(r"{}{}".format(str(uuid4()),img_extension), dic['image_data'])
    db.update_to_report(session["db"], dic['data'], dic['section_name'],img_path,int(dic['image_id']))
    return redirect(request.referrer)

@app.route('/generate_report', methods=['POST'])
def generate_report():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'POST':
        dic_data = {} 
        lst_data = db.get_all_report_data(session["db"])
        for data in lst_data:
            dic_data[data[2]] = [data[3],data[1]]
        
        doc = report.build_doc(dic_data)
        report.save(doc)
    return redirect(request.referrer)
    

"""
=======================================================
                Achievements Functions
=======================================================
"""

@app.route('/create_achievement', methods=['POST'])
def create_achievement():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'POST':
        text = request.form.get('achievement')
        if text:
            db.add_achievement(session["db"], text)

    return redirect(request.referrer)

@app.route('/edit_achievement', methods=['POST'])
def edit_achievement():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)
    
    if request.method == 'POST':
        achievement_id = request.values.get('check')
        db.update_achievement(session["db"], achievement_id)
        return ('', 204) 

@app.route('/delete_achievement', methods=['GET'])
def delete_achievement():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)
    
    if request.method == 'GET':
        achievement_id = request.values.get('id')
        db.delete_achievement(session["db"], achievement_id)
        return ('', 204) 

"""
=======================================================
                Search Functions
=======================================================
"""

@app.route('/search', methods=['GET','POST'])
def search():
    '''
    match[0] ==> data | match[1] ==> id_of_item | match[2] ==> table_name
    '''
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    if request.method == 'GET':
        return render_template('results.html', project=session["project"], username=session["username"])

    if request.method == 'POST':
        keyword = request.form.get('keyword')
        if keyword.replace(" ","") == "":
            return redirect(request.referrer)

        info = defaultdict(list)
        data = db.get_all_data(session["db"])
        matches = []
        for i,inf in enumerate(data):
            for detail in inf:
                if keyword.lower() in str(detail).lower():
                    if data[i][3]:
                        matches.append(data[i])
                    break

        print(matches)
        for match in matches:
            info[match[4]].append(db.get_data_by_table(session["db"], match[4],match[1]))
            print(info)
    return render_template('results.html', project=session["project"], username=session["username"],keyword=keyword,data_len=len(matches),data=info)

"""
=======================================================
                Exploits Functions
=======================================================
"""

@app.route('/exploits')
def exploits():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)
    
    exploits = db.get_all_exploits(session["db"])

    return render_template('exploits.html', project=session["project"], username=session["username"], exploits=exploits, exploits_len=len(exploits))

@app.route('/add_exploit',methods=['POST'])
def add_exploit():
    """
    Save new exploit to DB - if File has uploded ==> saves it to payloads dir
    Adding exploit to DB.
    """
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)
    
    dic = {}
    if request.method == 'POST':
        for key,val in request.form.items():
            dic[key] = val
        if request.files.get("exploit-file"):
            file = request.files.get("exploit-file")
            full_path, file_name = helper.save_file(file, helper.PAYLOAD_FILES.format(session["project"]))
            db.insert_new_standalone_file(session["db"], full_path, file_name, "Exploit File Added", session["username"])
        else:
            full_path = None
        db.insert_new_exploit(session["db"], dic['exploit-name'],dic['exploit-con'],full_path)

    return redirect(request.referrer)

@app.route('/update_exploit',methods=['POST'])
def update_exploit():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)
    
    exploit_name = request.form.get("exploit_name")
    exploit_data = request.form.get("exploit_data")
    exploit_id = request.form.get("exploit_id")
    if exploit_data and exploit_id and exploit_name:
        db.update_exploit(session["db"], exploit_id, exploit_name, exploit_data)

    return redirect(request.referrer)

@app.route('/delete_exploit',methods=['GET'])
def delete_exploit():
    """
    Changes exploit relevent to 0
    """
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)
    
    exploit_id = request.args.get("id")
    db.change_relevent_to_zero(session["db"], "exploits",exploit_id)
    
    return redirect(request.referrer)

"""
=======================================================
                Users Functions
=======================================================
"""

@app.route("/serverusers",methods=['GET'])
def serverusers():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    users = db.get_redeye_users()
    
    for i,user in enumerate(users):
        users[i] = users[i][:2] + ("*********************",) + users[i][3:] + ("RedTeam",)
        
    return render_template("serverusers.html", project=session["project"], username=session["username"], users=users)

@app.route('/add_user',methods=['POST'])
def add_user():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    username = request.form.get("username")
    password = request.form.get("password")
    user_id = db.add_new_user(username, password)

    return redirect(request.referrer)

@app.route('/update_user_name',methods=['POST'])
def update_user_name():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    dict = request.args.to_dict()
    db.update_user_details("username", dict["username"], dict["user_id"])

    return redirect(request.referrer)

@app.route('/update_password',methods=['POST'])
def update_password():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    dict = request.args.to_dict()
    db.update_user_details("password", dict["password"], dict["user_id"])

    return redirect(request.referrer)


@app.route('/delete_managment_user',methods=['POST'])
def delete_managment_user():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    dict = request.args.to_dict()
    db.delete_user_by_id(dict["user_id"])

    return redirect(request.referrer)


"""
=======================================================
                notebook Functions
=======================================================
"""

@app.route('/notebook',methods=['GET'])
def notebook():
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    # get all notebooks
    notebooks = db.get_all_notebooks(session["db"],session["uid"])
    return render_template('notebook.html', project=session["project"], username=session["username"],notebooks=notebooks)


@socketio.on('updateNoteName')
def updateNoteName(json):
    if not is_logged():
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    print(json)
    db.update_notebookName(session["db"],json["noteId"], json["data"])
    print(session)


"""
=======================================================
                Helpers Functions
=======================================================
"""
#### fix this function after added section id by daniel
def add_scan(file):
    nmap_dic = {}
    try:
        full_path, file_name = helper.save_file(file, helper.SCAN_FOLDER.format(session["project"]))
        if parse.check_nmap_file(full_path):
            if file_name:
                nmap_dic = parse.get_nmap_data(full_path)
                for ip_addr, data in nmap_dic.items():
                    vendor, hostname, lst_ports = data[0]["vendor"], data[0]["hostname"], data[1]["ports"]
                    section_id = helper.get_section_id(session["db"], ip_addr)
                    print(ip_addr)
                    if not db.check_if_server_exsist(session["db"], ip_addr):
                        if hostname != "":
                            server_id = db.create_new_server(session["db"], session["username"]
                            , ip_addr, hostname, vendor, 0, "Added from nmap scan",section_id)
                        else:
                            server_id = db.create_new_server(session["db"], session["username"]
                            , ip_addr, "Unknown", vendor, 0, "Added from nmap scan",section_id)
                        for data in lst_ports:
                            port_num, state, service = data["port"], data["state"], data["service"]
                            db.insert_new_port(session["db"], 
                                port_num, state, service, "", "server_id", server_id)
                    else:
                        server_id = db.get_server_id_by_ip(session["db"], ip_addr)[0][0]
                        exsist_ports = []
                        [exsist_ports.append(
                            s[1]) for s in db.get_ports_by_server_id(session["db"], server_id)]
                        for data in lst_ports:
                            port_num, state, service = data["port"], data["state"], data["service"]
                            if port_num not in exsist_ports:
                                db.insert_new_port(session["db"], 
                                    port_num, state, service, "", "server_id", server_id)

    except Exception as e:
        print("ERROR: Exception adding nmap scan: ", e)
        return 0
    return 1

"""
=======================================================
                Login & Project Functions
=======================================================
"""


@app.route('/login', methods=['GET', 'POST'])
def login():
    creds = request.form.to_dict()
    check_id = helper.check_login(creds)
    if creds and check_id:
        session["username"] = creds["username"]
        session["uid"] = check_id
        session["project"] = creds["project"] # TODO: Validate project existance.
        session["db"] = db.set_project_db(session["project"])
        session["project"] = helper.get_project_name(projects, session["project"])
        clients[session["uid"]] = socketio
        token = jwt.encode({'user': "{}-{}".format(creds['username'],check_id), 'exp': datetime.utcnow(
        ) + timedelta(hours=2)}, app.secret_key)
        resp = make_response(index(token.decode('UTF-8')))
        resp.set_cookie('reduser', token.decode('UTF-8'))
        return resp

    else:
        resp = make_response(render_template("login.html", projects=projects, show_create_project=IS_ENV_SAFE))
        resp.set_cookie('reduser', "")
        return resp

@app.route('/new_project', methods=['POST'])
def new_project():
    if not IS_ENV_SAFE:
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    data = request.form.to_dict()
    if (not data["name"] or "/" in data["name"]) or "\\" in data["name"] or "'" in data["name"] or \
       (not data["dbname"] or "/" in data["dbname"] or "\\" in data["dbname"] or "'" in data["dbname"]):
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE, msg="Lol, no.")
    
    if not data["dbname"].endswith(".db"):
        data["dbname"] += ".db"

    for project in projects:
        if data["dbname"] == project[1]:
            return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE, msg="DB name is already used.")
        elif data["name"] == project[2]:
            return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE, msg="Network name is taken.")

    db.insert_new_project(data["name"], data["dbname"])
    refresh_projects()
    resp = make_response(render_template("login.html", projects=projects, show_create_project=IS_ENV_SAFE))
    resp.set_cookie('reduser', "")
    init(app)
    return resp

def refresh_projects():
    global projects
    projects = db.get_projects()

def is_logged(logged=False):
    try:
        token = request.cookies['reduser']
        data = jwt.decode(token, app.secret_key)
        return True
    except Exception:
        try:
            data = jwt.decode(logged, app.secret_key)
            return True
        except:
            return False



"""
=======================================================
                Web Functions
=======================================================
"""

def emit_to_all_users(details, function_name):
    for uid in db.get_redeye_users():
        uid = uid[0]
        if str(uid) in clients.keys():
            print("uid: " + str(uid))
            print("room: " + clients[str(uid)])
            emit(function_name,details ,room=clients[str(uid)])

@socketio.on('socket_connection')
def socket_connection(msg):
    clients[str(session['uid'])] = request.sid

@app.after_request
def add_header(response):
    """
    Add headers to both force latest IE rendering engine or Chrome Frame,
    and also to cache the rendered page for 10 minutes.
    """
    response.headers["X-UA-Compatible"] = "IE=Edge,chrome=1"
    response.headers["Cache-Control"] = "public, max-age=0"
    return response

@app.route('/')
def index(logged=False):
    if not is_logged(logged):
        print("dsa")
        return render_template('login.html', projects=projects, show_create_project=IS_ENV_SAFE)

    comments = db.get_all_comments(session["db"])
    #print("logged: " + logged)
    return render_template('index.html', project=session["project"], username=session["username"], display_name=session["username"], comments=comments)

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

if __name__ == "__main__":
    # Run app.
    # only app run goes here
    helper.setGlobals()
    init(app)
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)