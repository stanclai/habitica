#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Phil Adams http://philadams.net

habitica: commandline interface for http://habitica.com
http://github.com/philadams/habitica

TODO:philadams add logging to .api
TODO:philadams get logger named, like requests!
"""


from bisect import bisect
import json
import logging
import netrc
import os.path
from time import sleep, time
from webbrowser import open_new_tab

from docopt import docopt

from . import api

from pprint import pprint

try:
    import ConfigParser as configparser
except:
    import configparser


VERSION = 'habitica version 0.0.12'
TASK_VALUE_BASE = 0.9747  # http://habitica.wikia.com/wiki/Task_Value
HABITICA_REQUEST_WAIT_TIME = 0.5  # time to pause between concurrent requests
HABITICA_TASKS_PAGE = '/#/tasks'
# https://trello.com/c/4C8w1z5h/17-task-difficulty-settings-v2-priority-multiplier
PRIORITY = {'easy': 1,
            'medium': 1.5,
            'hard': 2}
AUTH_CONF = os.path.expanduser('~') + '/.config/habitica/auth.cfg'
CACHE_CONF = os.path.expanduser('~') + '/.config/habitica/cache.cfg'

SECTION_CACHE_QUEST = 'Quest'


def load_auth(configfile):
    """Get authentication data from the AUTH_CONF file."""

    logging.debug('Loading habitica auth data from %s' % configfile)

    try:
        cf = open(configfile)
    except IOError:
        logging.error("Unable to find '%s'." % configfile)
        exit(1)

    config = configparser.SafeConfigParser()
    config.readfp(cf)

    cf.close()

    # Get data from config
    rv = {}
    try:
        rv = {'url': config.get('Habitica', 'url'),
              'x-api-user': config.get('Habitica', 'login'),
              'x-api-key': config.get('Habitica', 'password')}

    except configparser.NoSectionError:
        logging.error("No 'Habitica' section in '%s'" % configfile)
        exit(1)

    except configparser.NoOptionError as e:
        logging.error("Missing option in auth file '%s': %s"
                      % (configfile, e.message))
        exit(1)

    # Return auth data as a dictionnary
    return rv


def load_cache(configfile):
    logging.debug('Loading cached config data (%s)...' % configfile)

    defaults = {'quest_key': '',
                'quest_s': 'Not currently on a quest'}

    cache = configparser.SafeConfigParser(defaults)
    cache.read(configfile)

    if not cache.has_section(SECTION_CACHE_QUEST):
        cache.add_section(SECTION_CACHE_QUEST)

    return cache


def update_quest_cache(configfile, **kwargs):
    logging.debug('Updating (and caching) config data (%s)...' % configfile)

    cache = load_cache(configfile)

    for key, val in kwargs.items():
        cache.set(SECTION_CACHE_QUEST, key, val)

    with open(configfile, 'wb') as f:
        cache.write(f)

    cache.read(configfile)

    return cache


def get_task_ids(tids):
    """
    handle task-id formats such as:
        habitica todos done 3
        habitica todos done 1,2,3
        habitica todos done 2 3
        habitica todos done 1-3,4 8
    tids is a seq like (last example above) ('1-3,4' '8')
    """
    logging.debug('raw task ids: %s' % tids)
    task_ids = []
    for raw_arg in tids:
        for bit in raw_arg.split(','):
            if '-' in bit:
                start, stop = [int(e) for e in bit.split('-')]
                task_ids.extend(range(start, stop + 1))
            else:
                task_ids.append(int(bit))
    return [e - 1 for e in set(task_ids)]


def updated_task_list(tasks, tids):
    for tid in sorted(tids, reverse=True):
        del(tasks[tid])
    return tasks


def print_task_list(tasks):
    for i, task in enumerate(tasks):
        completed = 'x' if task['completed'] else ' '
        print('[%s] %s %s' % (completed, i + 1, task['text'].encode('utf8')))


def qualitative_task_score_from_value(value):
    # task value/score info: http://habitica.wikia.com/wiki/Task_Value
    scores = ['*', '**', '***', '****', '*****', '******', '*******']
    breakpoints = [-20, -10, -1, 1, 5, 10]
    return scores[bisect(breakpoints, value)]


def cli():
    """Habitica command-line interface.

    Usage: habitica [--version] [--help]
                    <command> [<args>...] [--difficulty=<d>]
                    [--verbose | --debug]

    Options:
      -h --help         Show this screen
      --version         Show version
      --difficulty=<d>  (easy | medium | hard) [default: easy]
      --verbose         Show some logging information
      --debug           Some all logging information

    The habitica commands are:
      status                 Show HP, XP, GP, and more
      habits                 List habit tasks
      habits up <task-id>    Up (+) habit <task-id>
      habits down <task-id>  Down (-) habit <task-id>
      dailies                List daily tasks
      dailies done           Mark daily <task-id> complete
      dailies undo           Mark daily <task-id> incomplete
      todos                  List todo tasks
      todos done <task-id>   Mark one or more todo <task-id> completed
      todos add <task>       Add todo with description <task>
      server                 Show status of Habitica service
      home                   Open tasks page in default browser
      item [type]            Show item types, or specific items of given type
      feed                   Feed all food to matching pets
      hatch                  Use potions to hatch eggs, sell unneeded eggs
      sell [type]            Sell all potions of type or "all"

    For `habits up|down`, `dailies done|undo`, and `todos done`, you can pass
    one or more <task-id> parameters, using either comma-separated lists or
    ranges or both. For example, `todos done 1,3,6-9,11`.
    """

    # set up args
    args = docopt(cli.__doc__, version=VERSION)

    # set up logging
    if args['--verbose']:
        logging.basicConfig(level=logging.INFO)
    if args['--debug']:
        logging.basicConfig(level=logging.DEBUG)

    logging.debug('Command line args: {%s}' %
                  ', '.join("'%s': '%s'" % (k, v) for k, v in args.items()))

    # Set up auth
    auth = load_auth(AUTH_CONF)

    # Prepare cache
    cache = load_cache(CACHE_CONF)

    # instantiate api service
    hbt = api.Habitica(auth=auth)

    # GET server status
    if args['<command>'] == 'server':
        server = hbt.status()
        if server['status'] == 'up':
            print('Habitica server is up')
        else:
            print('Habitica server down... or your computer cannot connect')

    # open HABITICA_TASKS_PAGE
    elif args['<command>'] == 'home':
        home_url = '%s%s' % (auth['url'], HABITICA_TASKS_PAGE)
        print('Opening %s' % home_url)
        open_new_tab(home_url)

    # GET item lists
    elif args['<command>'] == 'item':
        user = hbt.user()
        items = user.get('items', [])
        if len(args['<args>']):
            name = args['<args>'][0]
            for item in items.get(name, []):
                count = items[name][item]
                if count:
                    print('%d %s' % (count, item))
        else:
            for item in items:
                print('%s' % (item))

    elif args['<command>'] == 'feed':
        feeding = {
                    'Saddle':           'ignore',
                    'Meat':             'Base',
                    'CottonCandyBlue':  'CottonCandyBlue',
                    'CottonCandyPink':  'CottonCandyPink',
                    'Honey':            'Golden',
                    'Milk':             'White',
                    'Strawberry':       'Red',
                    'Chocolate':        'Shade',
                    'Fish':             'Skeleton',
                    'Potatoe':          'Desert',
                    'RottenMeat':       'Zombie',
                  }
        user = hbt.user()
        refreshed = True

        while refreshed:
            refreshed = False
            items = user.get('items', [])
            foods = items['food']
            pets = items['pets']
            mounts = items['mounts']
            for food in foods:
                # Handle seasonal foods that encode matching pet in name.
                if '_' in food:
                    best = food.split('_',1)[1]
                    if not food in feeding:
                        feeding[food] = best

                # Skip foods we don't have any of.
                if items['food'][food] <= 0:
                    continue

                # Find best pet to feed to.
                suffix = feeding.get(food, None)
                if suffix == None:
                    print("Unknown food: %s" % (food))
                    continue
                if suffix == 'ignore':
                    continue

                mouth = None
                best = 0
                for pet in pets:
                    fed = items['pets'][pet]

                    # Unhatched pet.
                    if fed <= 0:
                        #print("Unhatched: %s" % (pet))
                        continue
                    # Unfeedable pet.
                    if items['mounts'].get(pet, 0) == 1 and fed == 5:
                        #print("Has mount: %s" % (pet))
                        continue
                    # Not best food match.
                    if not pet.endswith('-%s' % (suffix)):
                        #print("Not a match for %s: %s" % (food, pet))
                        continue

                    if fed > best:
                        best = fed
                        mouth = pet

                if mouth:
                    print("Feeding %s to %s" % (food, " ".join(mouth.split('-')[::-1])))
                    batch = api.Habitica(auth=auth, resource="user", aspect="batch-update?_v=137&data=%d" % (int(time() * 1000)))
                    user = batch(_method='post', ops=[{'op':"feed", 'params':{"pet":mouth, "food":food}}])
                    refreshed = True
                    break

    elif args['<command>'] == 'hatch':
        def hatch_refresh(user):
            items = user.get('items', [])
            pets = items['pets']
            mounts = items['mounts']
            eggs = items['eggs']
            potions = items['hatchingPotions']
            return (items, pets, mounts, eggs, potions)

        user = hbt.user()
        refreshed = True
        # list of kinds of pets (disregarding Magic Potion ones)
        kinds = [ 'Base', 'CottonCandyBlue', 'CottonCandyPink',
                  'Golden', 'White', 'Red', 'Shade', 'Skeleton',
                  'Desert', 'Zombie' ]

        while refreshed:
            refreshed = False
            items, pets, mounts, eggs, potions = hatch_refresh(user)

            for egg in eggs:
                # Skip eggs we don't have.
                if eggs[egg] == 0:
                    continue

                # Used to keep count of number of eggs we need
                need = 0

                creatures = []
                for kind in kinds:
                    creatures.append('%s-%s' % (egg, kind))

                for creature in creatures:
                    # This pet is already hatched.
                    if pets.get(creature, 0) != -1:
                        continue

                    potion = creature.split('-')[-1]
                    # Missing the potion needed for this creature.
                    if potion not in potions:
                        continue

                    print("Hatching a %s %s" % (potion, egg))
                    batch = api.Habitica(auth=auth, resource="user", aspect="batch-update?_v=137&data=%d" % (int(time() * 1000)))
                    user = batch(_method='post', ops=[{'op':"hatch", 'params':{"egg":egg, "hatchingPotion":potion}}])
                    refreshed = True
                    items, pets, mounts, eggs, potions = hatch_refresh(user)
                    if pets.get(creature, 0) == -1:
                        raise ValueError("failed to hatch %s" % (creature))

                needing = []
                # How many eggs do we need for the future?
                for creature in creatures:
                    if mounts.get(creature, 0) == 0:
                        need += 1
                        needing.append('%s [m]' % creature)
                    if pets.get(creature, 0) == -1:
                        need += 1
                        needing.append('%s [p]' % creature)

                needed = ''
                if needing:
                    needed = ' (%s)' % ', '.join(needing)
                print("%s: need %d%s of %d" % (egg, need, needed, eggs[egg]))

                # Sell unneeded eggs.
                sell = eggs[egg] - need
                if sell > 0:
                    before = eggs[egg]
                    print("Selling %d %s egg%s" % (sell, egg,
                                                   "" if sell == 1 else "s"))
                    batch = api.Habitica(auth=auth, resource="user", aspect="batch-update?_v=137&data=%d" % (int(time() * 1000)))
                    ops = []
                    for i in range(sell):
                        ops.append({'op':"sell", 'params':{'type':'eggs', 'key':egg}})
                    user = batch(_method='post', ops=ops)
                    refreshed = True
                    items, pets, mounts, eggs, potions = hatch_refresh(user)
                    if eggs.get(egg, 0) != before - sell:
                        raise ValueError("failed to sell %s egg" % (egg))

    elif args['<command>'] == 'sell':
        # list of kinds of potions (disregarding Magic ones)
        kinds = [ 'Base', 'CottonCandyBlue', 'CottonCandyPink',
                  'Golden', 'White', 'Red', 'Shade', 'Skeleton',
                  'Desert', 'Zombie' ]

        selling = args['<args>']
        if selling == ['all']:
            selling = kinds

        def hatch_refresh(user):
            items = user.get('items', [])
            potions = items['hatchingPotions']
            return (potions)

        user = hbt.user()
        refreshed = True

        while refreshed:
            refreshed = False
            potions = hatch_refresh(user)
            for sell in selling:
                if sell not in kinds:
                    print("That isn't a valid kind of potion.")
                if sell not in potions:
                    print("You don't have any of those.")
                    continue
                if potions[sell] > 0:
                    print("Selling %d %s potion%s" % (potions[sell], sell,
                            "" if options[sell] == 1 else "s"))
                    batch = api.Habitica(auth=auth, resource="user", aspect="batch-update?_v=137&data=%d" % (int(time() * 1000)))
                    ops = []
                    for i in range(potions[sell]):
                        ops.append({'op':"sell", 'params':{"type":'hatchingPotions', "key":sell}})
                    user = batch(_method='post', op="sell", ops=ops)
                    refreshed = True
                    potions = hatch_refresh(user)

    # GET user
    elif args['<command>'] == 'status':

        # gather status info
        user = hbt.user()
        party = hbt.groups.party()
        stats = user.get('stats', '')
        items = user.get('items', '')
        food_count = sum(items['food'].values())

        # gather quest progress information (yes, janky. the API
        # doesn't make this stat particularly easy to grab...).
        # because hitting /content downloads a crapload of stuff, we
        # cache info about the current quest in cache.
        quest = 'Not currently on a quest'
        if (party is not None and
                party.get('quest', '') and
                party.get('quest').get('active')):

            quest_key = party['quest']['key']

            if cache.get(SECTION_CACHE_QUEST, 'quest_key') != quest_key:
                # we're on a new quest, update quest key
                logging.info('Updating quest information...')
                content = hbt.content()
                quest_type = ''
                quest_max = '-1'
                quest_title = content['quests'][quest_key]['text']

                # if there's a content/quests/<quest_key/collect,
                # then drill into .../collect/<whatever>/count and
                # .../collect/<whatever>/text and get those values
                if content.get('quests', {}).get(quest_key, {}).get('collect'):
                    logging.debug("\tOn a collection type of quest")
                    quest_type = 'collect'
                    clct = content['quests'][quest_key]['collect'].values()[0]
                    quest_max = clct['count']
                # else if it's a boss, then hit up
                # content/quests/<quest_key>/boss/hp
                elif content.get('quests', {}).get(quest_key, {}).get('boss'):
                    logging.debug("\tOn a boss/hp type of quest")
                    quest_type = 'hp'
                    quest_max = content['quests'][quest_key]['boss']['hp']

                # store repr of quest info from /content
                cache = update_quest_cache(CACHE_CONF,
                                           quest_key=str(quest_key),
                                           quest_type=str(quest_type),
                                           quest_max=str(quest_max),
                                           quest_title=str(quest_title))

            # now we use /party and quest_type to figure out our progress!
            quest_type = cache.get(SECTION_CACHE_QUEST, 'quest_type')
            if quest_type == 'collect':
                qp_tmp = party['quest']['progress']['collect']
                quest_progress = qp_tmp.values()[0]['count']
            else:
                quest_progress = party['quest']['progress']['hp']

            quest = '%s/%s "%s"' % (
                    str(int(quest_progress)),
                    cache.get(SECTION_CACHE_QUEST, 'quest_max'),
                    cache.get(SECTION_CACHE_QUEST, 'quest_title'))

        # prepare and print status strings
        title = 'Level %d %s' % (stats['lvl'], stats['class'].capitalize())
        health = '%d/%d' % (stats['hp'], stats['maxHealth'])
        xp = '%d/%d' % (int(stats['exp']), stats['toNextLevel'])
        mana = '%d/%d' % (int(stats['mp']), stats['maxMP'])
        gp = float(stats.get('gp', "0.0"))
        gold = int(gp)
        silver = int((gp - int(gp)) * 100)
        gems = int(stats.get('gems', 0)) # where is this?!
        currency = 'Gold: %d  Silver: %d  Gems: %d' % (gold, silver, gems)
        currentPet = items.get('currentPet', '')
        pet = '%s (%d food items)' % (currentPet, food_count)
        mount = items.get('currentMount', '')
        summary_items = ('health', 'xp', 'mana', 'currency', 'quest', 'pet',
                         'mount')
        len_ljust = max(map(len, summary_items)) + 1
        print('-' * len(title))
        print(title)
        print('-' * len(title))
        print('%s %s' % ('Health:'.rjust(len_ljust, ' '), health))
        print('%s %s' % ('XP:'.rjust(len_ljust, ' '), xp))
        print('%s %s' % ('Mana:'.rjust(len_ljust, ' '), mana))
        print('%s %s' % ('Currency:'.rjust(len_ljust, ' '), currency))
        print('%s %s' % ('Pet:'.rjust(len_ljust, ' '), pet))
        print('%s %s' % ('Mount:'.rjust(len_ljust, ' '), mount))
        print('%s %s' % ('Quest:'.rjust(len_ljust, ' '), quest))

    # GET/POST habits
    elif args['<command>'] == 'habits':
        habits = hbt.user.tasks(type='habit')
        if 'up' in args['<args>']:
            tids = get_task_ids(args['<args>'][1:])
            for tid in tids:
                tval = habits[tid]['value']
                hbt.user.tasks(_id=habits[tid]['id'],
                               _direction='up', _method='post')
                print('incremented task \'%s\''
                      % habits[tid]['text'].encode('utf8'))
                habits[tid]['value'] = tval + (TASK_VALUE_BASE ** tval)
                sleep(HABITICA_REQUEST_WAIT_TIME)
        elif 'down' in args['<args>']:
            tids = get_task_ids(args['<args>'][1:])
            for tid in tids:
                tval = habits[tid]['value']
                hbt.user.tasks(_id=habits[tid]['id'],
                               _direction='down', _method='post')
                print('decremented task \'%s\''
                      % habits[tid]['text'].encode('utf8'))
                habits[tid]['value'] = tval - (TASK_VALUE_BASE ** tval)
                sleep(HABITICA_REQUEST_WAIT_TIME)
        for i, task in enumerate(habits):
            score = qualitative_task_score_from_value(task['value'])
            print('[%s] %s %s' % (score, i + 1, task['text'].encode('utf8')))

    # GET/PUT tasks:daily
    elif args['<command>'] == 'dailies':
        dailies = hbt.user.tasks(type='daily')
        if 'done' in args['<args>']:
            tids = get_task_ids(args['<args>'][1:])
            for tid in tids:
                hbt.user.tasks(_id=dailies[tid]['id'],
                               _direction='up', _method='post')
                print('marked daily \'%s\' completed'
                      % dailies[tid]['text'].encode('utf8'))
                dailies[tid]['completed'] = True
                sleep(HABITICA_REQUEST_WAIT_TIME)
        elif 'undo' in args['<args>']:
            tids = get_task_ids(args['<args>'][1:])
            for tid in tids:
                hbt.user.tasks(_id=dailies[tid]['id'],
                               _method='put', completed=False)
                print('marked daily \'%s\' incomplete'
                      % dailies[tid]['text'].encode('utf8'))
                dailies[tid]['completed'] = False
                sleep(HABITICA_REQUEST_WAIT_TIME)
        print_task_list(dailies)

    # GET tasks:todo
    elif args['<command>'] == 'todos':
        todos = [e for e in hbt.user.tasks(type='todo')
                 if not e['completed']]
        if 'done' in args['<args>']:
            tids = get_task_ids(args['<args>'][1:])
            for tid in tids:
                hbt.user.tasks(_id=todos[tid]['id'],
                               _direction='up', _method='post')
                print('marked todo \'%s\' complete'
                      % todos[tid]['text'].encode('utf8'))
                sleep(HABITICA_REQUEST_WAIT_TIME)
            todos = updated_task_list(todos, tids)
        elif 'add' in args['<args>']:
            ttext = ' '.join(args['<args>'][1:])
            hbt.user.tasks(type='todo',
                           text=ttext,
                           priority=PRIORITY[args['--difficulty']],
                           _method='post')
            todos.insert(0, {'completed': False, 'text': ttext})
            print('added new todo \'%s\'' % ttext.encode('utf8'))
        print_task_list(todos)


if __name__ == '__main__':
    cli()
