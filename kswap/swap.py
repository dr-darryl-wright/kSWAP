import os
import csv
import ujson
import sqlite3

class Classification(object):
  def __init__(self,
               id,
               user_id,
               subject_id,
               annotation,
               label_map):
      
    self.id = int(id)
    try:
      self.user_id = int(user_id)
    except ValueError:
      self.user_id = user_id
    self.subject_id = int(subject_id)
    self.label_map  = label_map
    self.label = self.parse(annotation)

  def parse(self, annotation):
    value = annotation[0]['value']
    if value in self.label_map.keys():
      return self.label_map[value]
    else:
      raise ValueError('Annotation value {} not recognised.'.format(value))

class User(object):
  def __init__(self,
               user_id,
               classes,
               user_default=None):

    self.user_id = user_id
    self.classes = classes
    self.k = len(classes)
    if user_default:
      self.user_score = user_default
    else:
      self.initialise_user_score()
    self.confusion_matrix = {'n_seen': [0]*self.k, 'n_gold': [0]*self.k}
    self.history = [('_', self.user_score)]
  
  def initialise_user_score(self):
    self.user_score = {}
    for i in range(self.k):
      self.user_score[self.classes[i]] = 1 / float(self.k)
  
  def dump(self):
    return (self.user_id,
            ujson.dumps(self.user_score),
            ujson.dumps(self.confusion_matrix),
            ujson.dumps(self.history))

class Subject(object):
  def __init__(self,
               subject_id,
               p0,
               classes,
               gold_label=-1,
               epsilon=1e-9):
      
    self.subject_id = subject_id
    self.score = p0
    self.classes = classes
    self.k = len(self.classes)
    self.gold_label = gold_label
    self.epsilon = epsilon
    self.retired = False
    self.retired_as = None
    self.seen = 0
    self.history = [('_', '_', '_', self.score)]

  def update_score(self, label, user):
    if label == 0:
      self.score = (self.score \
                 * (1 - user.user_score[self.classes[1]])) \
                 / (self.score \
                 * (1 - user.user_score[self.classes[1]]) \
                 + user.user_score[self.classes[0]] \
                 * (1-self.score) \
                 + self.epsilon)
    elif label == 1:
      self.score = (self.score \
                 * user.user_score[self.classes[1]]) \
                 / (self.score \
                 * user.user_score[self.classes[1]] \
                 + (1-user.user_score[self.classes[0]]) \
                 * (1-self.score)
                 + self.epsilon)
    
    self.history.append((user.user_id, user.user_score, label, self.score))
    self.seen += 1

  def dump(self):
    return (self.subject_id, \
            self.gold_label, \
            self.score, \
            self.retired, \
            self.retired_as, \
            self.seen, \
            ujson.dumps(self.history))

class SWAP(object):
  def __init__(self,
               config=None,
               timeout=10):
      
    self.users = {}
    self.subjects = {}
    self.objects = {}
    self.config=config
    self.last_id = 0
    self.seen = set([])
    self.db_exists = False
    self.timeout = timeout # wait x seconds to acquire db connection
    try:
      self.create_db()
    except sqlite3.OperationalError:
      self.db_exists = True
      
  def connect_db(self):
    return sqlite3.connect(self.config.db_path+self.config.db_name, timeout=self.timeout)

  def create_db(self):
    conn = self.connect_db()
    conn.execute('CREATE TABLE users (user_id PRIMARY KEY, user_score, ' +\
                 'confusion_matrix, history)')

    conn.execute('CREATE TABLE subjects (subject_id PRIMARY KEY, ' +\
                 'gold_label, score, retired, retired_as, seen ,history)')
                 
    conn.execute('CREATE TABLE thresholds (thresholds)')

    conn.execute('CREATE TABLE config (id PRIMARY KEY, user_default, ' +\
                 'workflow, p0, gamma, retirement_limit, db_path, ' +\
                 'db_name, timeout, last_id, seen)')

    conn.close()

  def load_users(self, users):
    for user in users:
      user_score = ujson.loads(user['user_score'])
      self.users[user['user_id']] = User(user_id=user['user_id'],
                                         classes=self.config.classes,
                                         user_default=user_score)
      self.users[user['user_id']].confusion_matrix = ujson.loads(user['confusion_matrix'])
      self.users[user['user_id']].history = ujson.loads(user['history'])

  def load_subjects(self, subjects):
    for subject in subjects:
      self.subjects[subject['subject_id']] = Subject(subject_id=subject['subject_id'],
                                                     classes=self.config.classes,
                                                     p0=self.config.p0)
      self.subjects[subject['subject_id']].score = subject['score']
      self.subjects[subject['subject_id']].gold_label = subject['gold_label']
      self.subjects[subject['subject_id']].retired = subject['retired']
      self.subjects[subject['subject_id']].retired_as = subject['retired_as']
      self.subjects[subject['subject_id']].seen = subject['seen']
      self.subjects[subject['subject_id']].history = ujson.loads(subject['history'])

  def load(self):
    def it(rows):
      for item in rows:
        yield dict(item)
    
    conn = self.connect_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    #try:
    c.execute('SELECT * FROM config')
    config = dict(c.fetchone())
                 
    swap = SWAP(config=self.config,
                timeout=config['timeout'])
                  
    swap.last_id = config['last_id']
    swap.seen = set(ujson.loads(config['seen']))
  
    c.execute('SELECT * FROM users')
    swap.load_users(it(c.fetchall()))
    
    c.execute('SELECT * FROM subjects')
    swap.load_subjects(it(c.fetchall()))
      
    #except TypeError as e:
    #  print(e)
    #  swap = SWAP(config=self.config)
    #
    #  swap.last_id = self.last_id
    #  swap.seen = self.seen
    #  c.execute('SELECT * FROM subjects')
    #  swap.load_subjects(it(c.fetchall()))

    conn.close()

    return swap

  def dump_users(self):
    users = []
    for u in self.users.keys():
      users.append(self.users[u].dump())
    return users

  def dump_subjects(self):
    subjects = []
    for s in self.subjects.keys():
      subjects.append(self.subjects[s].dump())
    return subjects
  
  def dump_objects(self):
    objects = []
    for o in self.objects.keys():
      objects.append(self.objects[o].dump())
    return objects

  def save(self):
    conn = self.connect_db()
    c = conn.cursor()

    def zip_name(data):
      return [d.values() for d in data]

    #if self.db_exists:
    c.executemany('INSERT OR REPLACE INTO users VALUES (?,?,?,?)',
                  self.dump_users())

    c.executemany('REPLACE INTO subjects VALUES (?,?,?,?,?,?,?)',
                    self.dump_subjects())

    c.execute('INSERT OR REPLACE INTO config VALUES (?,?,?,?,?,?,?,?,?,?,?)',
             (0, ujson.dumps(self.config.user_default), self.config.workflow,
              self.config.p0, self.config.gamma, self.config.retirement_limit,
              self.config.db_path, self.config.db_name, self.timeout,
              self.last_id, ujson.dumps(self.seen)))
    
    #else:
    #  c.executemany('INSERT INTO users VALUES (?,?,?,?)',
    #                self.dump_users())
    
    #  c.executemany('INSERT INTO subjects VALUES (?,?,?,?,?,?,?)',
    #                self.dump_subjects())
    
    conn.commit()
    conn.close()

  def process_classification(self, cl, online=False):
    # check user is known
    try:
      self.users[cl.user_id]
    except KeyError:
      self.users[cl.user_id] = User(user_id = cl.user_id,
                                    classes = self.config.classes,
                                    user_default = self.config.user_default)
    # check subject is known
    try:
      self.subjects[cl.subject_id]
    except KeyError:
      self.subjects[cl.subject_id] = Subject(subject_id = cl.subject_id,
                                             p0 = self.config.p0,
                                             classes = self.config.classes)


    self.subjects[cl.subject_id].update_score(cl.label, self.users[cl.user_id])

    if self.subjects[cl.subject_id].gold_label in (0,1) and online:
      gold_label = self.subjects[cl.subject_id].gold_label
      confusion_matrix = self.users[cl.user_id].confusion_matrix
      confusion_matrix['n_gold'][gold_label] += 1
      if gold_label == cl.label:
        confusion_matrix['n_seen'][cl.label] += 1
      try:
        score0=(confusion_matrix['n_seen'][0] + self.config.gamma) / (confusion_matrix['n_gold'][0] + 2.0*self.config.gamma)
      except ZeroDivisionError:
        score0=self.user_default[self.config.classes[0]]
      try:
        score1=(confusion_matrix['n_seen'][1] + self.config.gamma) / (confusion_matrix['n_gold'][1] + 2.0*self.config.gamma)
      except ZeroDivisionError:
        score1=self.user_default[self.config.classes[1]]

      self.users[cl.user_id].user_score = {self.config.classes[0]: score0, self.config.classes[1]: score1}
    self.users[cl.user_id].history.append((cl.subject_id, self.users[cl.user_id].user_score))

  def retire(self, subject_batch):
    to_retire = []
    for subject_id in subject_batch:
      try:
        subject = self.subjects[subject_id]
      except KeyError:
        print('Subject {} is missing.'.format(subject_id))
        continue
      if subject.gold_label in (0,1):
        # if this is a gold standard image never retire
        continue
      if subject.score < self.config.thresholds[0]:
        subject.retired = True
        subject.retired_as = 0
        to_retire.append(subject_id)
      elif subject.score > self.config.thresholds[1]:
        subject.retired = True
        subject.retired_as = 1
        to_retire.append(subject_id)
    return to_retire
    
  def retire_classification_count(self, subject_batch):
  
    def majority_vote(sequence):
      occurence_count = Counter(sequence)
      return occurence_count.most_common(1)[0][0]
    
    to_retire = []
    for subject_id in subject_batch:
      try:
        subject = self.subjects[subject_id]
      except KeyError:
        print('Subject {} is missing.'.format(subject_id))
        continue
      if subject.seen >= self.config.retirement_limit:
        subject.retired = True
        subject.retired_as = majority_vote([h[2] for h in subject.history])
        to_retire.append(subject_id)
    return to_retire

  def process_classifications_from_csv_dump(self, path, online=False):
    with open(path, 'r') as csvdump:
      reader = csv.DictReader(csvdump)
      for row in reader:
        id = int(row['classification_id'])
        try:
          assert int(row['workflow_id']) == self.config.workflow
          # ignore repeat classifications of the same subject
          ujson.loads(row['metadata'])['seen_before']
          continue
        except KeyError as e:
          pass
        except AssertionError as e:
          print(e, row)
          continue
        try:
          user_id = int(row['user_id'])
        except ValueError:
          user_id = row['user_name']
        subject_id = int(row['subject_ids'])
        annotation = ujson.loads(row['annotations'])
        try:
          cl = Classification(id,
                              user_id,
                              subject_id,
                              annotation,
                              label_map=self.config.label_map)
        except ValueError:
          continue
        self.process_classification(cl, online)
        self.last_id = id
        self.seen.add(id)
    try:
      self.retire(self.subjects.keys())
    except TypeError:
      self.retire_classification_count(self.subjects.keys())

  def get_golds(self, path):
    with open(path,'r') as csvdump:
      reader = csv.DictReader(csvdump)
      for row in reader:
        subject_id = int(row['subject_id'])
        gold_label = int(row['gold'])
        self.subjects[subject_id] = Subject(subject_id,
                                            classes = self.config.classes,
                                            p0 = self.config.p0,
                                            gold_label = gold_label)

  def apply_golds(self, path):
    with open(path, 'r') as csvdump:
      reader = csv.DictReader(csvdump)
      for row in reader:
        id = int(row['classification_id'])
        try:
          user_id = int(row['user_id'])
        except ValueError:
          user_id = row['user_name']
        subject_id = int(row['subject_ids'])
        annotation = ujson.loads(row['annotations'])
        try:
          cl = Classification(id,
                              user_id,
                              subject_id,
                              annotation,
                              label_map=self.config.label_map)
        except ValueError:
          continue
        try:
          self.users[cl.user_id]
        except KeyError:
          self.users[cl.user_id] = User(user_id = cl.user_id,
                                        classes = self.config.classes,
                                        user_default = self.config.user_default)
        
        try:
          gold_label = self.subjects[cl.subject_id].gold_label
          confusion_matrix = self.users[cl.user_id].confusion_matrix
          assert gold_label in (0,1)
          confusion_matrix['n_gold'][gold_label] += 1
          if gold_label == cl.label:
            confusion_matrix['n_seen'][cl.label] += 1
          try:
            score0=(confusion_matrix['n_seen'][0] + self.config.gamma) / (confusion_matrix['n_gold'][0] + 2.0*self.config.gamma)
          except ZeroDivisionError:
            score0=self.config.user_default[self.config.classes[0]]
          try:
            score1=(confusion_matrix['n_seen'][1] + self.config.gamma) / (confusion_matrix['n_gold'][1] + 2.0*self.config.gamma)
          except ZeroDivisionError:
            score1=self.config.user_default[self.config.classes[1]]

          self.users[cl.user_id].user_score = {self.config.classes[0]: score0, self.config.classes[1]: score1}
        except AssertionError as e:
          continue
        except KeyError as e:
          continue

  def run_offline(self, gold_csv, classification_csv):
    self.get_golds(gold_csv)
    self.apply_golds(classification_csv)
    self.process_classifications_from_csv_dump(classification_csv)

  def run_online(self, gold_csv, classification_csv):
    self.get_golds(gold_csv)
    self.process_classifications_from_csv_dump(classification_csv, online=True)
