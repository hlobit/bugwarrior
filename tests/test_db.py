import copy
import unittest

import taskw.task

from bugwarrior import db
from bugwarrior.config.load import BugwarriorConfigParser

from .base import ConfigTest


class TestMergeLeft(unittest.TestCase):
    def setUp(self):
        self.issue_dict = {'annotations': ['testing']}

    def assertMerged(self, local, remote, **kwargs):
        db.merge_left('annotations', local, remote, **kwargs)
        self.assertEqual(local, remote)

    def test_with_dict(self):
        self.assertMerged({}, self.issue_dict)

    def test_with_taskw(self):
        self.assertMerged(taskw.task.Task({}), self.issue_dict)

    def test_already_in_sync(self):
        self.assertMerged(self.issue_dict, self.issue_dict)

    def test_rough_equality_hamming_false(self):
        """ When hamming=False, rough equivalents are duplicated. """
        remote = {'annotations': ['\n  testing  \n']}

        db.merge_left('annotations', self.issue_dict, remote, hamming=False)
        self.assertEqual(len(self.issue_dict['annotations']), 2)

    def test_rough_equality_hamming_true(self):
        """ When hamming=True, rough equivalents are not duplicated. """
        remote = {'annotations': ['\n  testing  \n']}

        db.merge_left('annotations', self.issue_dict, remote, hamming=True)
        self.assertEqual(len(self.issue_dict['annotations']), 1)


class TestReplaceLeft(unittest.TestCase):
    def setUp(self):
        self.issue_dict = {'tags': ['test', 'test2']}
        self.remote = {'tags': ['remote_tag1', 'remote_tag2']}

    def assertReplaced(self, local, remote, **kwargs):
        db.replace_left('tags', local, remote, **kwargs)
        self.assertEqual(local, remote)

    def test_with_dict(self):
        self.assertReplaced({}, self.issue_dict)

    def test_with_taskw(self):
        self.assertReplaced(taskw.task.Task({}), self.issue_dict)

    def test_already_in_sync(self):
        self.assertReplaced(self.issue_dict, self.issue_dict)

    def test_replace(self):
        self.assertReplaced(self.issue_dict, self.remote)

    def test_replace_with_keeped_item(self):
        """ When keeped_item is set, all item in this list are keeped """
        result = {'tags': ['test', 'remote_tag1', 'remote_tag2']}
        print(self.issue_dict)
        keeped_items = ['test']
        db.replace_left('tags', self.issue_dict, self.remote, keeped_items)
        self.assertEqual(self.issue_dict, result)


class TestSynchronize(ConfigTest):

    def test_synchronize(self):

        def remove_non_deterministic_keys(tasks):
            for status in ['pending', 'completed']:
                for task in tasks[status]:
                    del task['modified']
                    del task['entry']
                    del task['uuid']

            return tasks

        def get_tasks(tw):
            return remove_non_deterministic_keys(tw.load_tasks())

        self.config = BugwarriorConfigParser()
        self.config.add_section('general')
        self.config.set('general', 'targets', 'my_service')
        self.config.set('general', 'taskrc', self.taskrc)
        self.config.set('general', 'static_fields', 'project, priority')
        self.config.add_section('my_service')
        self.config.set('my_service', 'service', 'github')
        self.config.set('my_service', 'github.login', 'ralphbean')
        self.config.set('my_service', 'github.username', 'ralphbean')
        self.config.set('my_service', 'github.password', 'abc123')
        bwconfig = self.validate()

        tw = taskw.TaskWarrior(self.taskrc)
        self.assertEqual(tw.load_tasks(), {'completed': [], 'pending': []})

        issue = {
            'description': 'Blah blah blah. ☃',
            'project': 'sample_project',
            'githubtype': 'issue',
            'githuburl': 'https://example.com',
            'priority': 'M',
        }

        # TEST NEW ISSUE AND EXISTING ISSUE.
        for _ in range(2):
            # Use an issue generator with two copies of the same issue.
            # These should be de-duplicated in db.synchronize before
            # writing out to taskwarrior.
            # https://github.com/ralphbean/bugwarrior/issues/601
            issue_generator = iter((issue, issue,))
            db.synchronize(issue_generator, bwconfig, 'general')

            self.assertEqual(get_tasks(tw), {
                'completed': [],
                'pending': [{
                    'project': 'sample_project',
                    'priority': 'M',
                    'status': 'pending',
                    'description': 'Blah blah blah. ☃',
                    'githuburl': 'https://example.com',
                    'githubtype': 'issue',
                    'id': 1,
                    'urgency': 4.9,
                }]})

        # TEST CHANGED ISSUE.
        issue['description'] = 'Yada yada yada.'

        # Change static field
        issue['project'] = 'other_project'

        db.synchronize(iter((issue,)), bwconfig, 'general')

        self.assertEqual(get_tasks(tw), {
            'completed': [],
            'pending': [{
                'priority': 'M',
                'project': 'sample_project',
                'status': 'pending',
                'description': 'Yada yada yada.',
                'githuburl': 'https://example.com',
                'githubtype': 'issue',
                'id': 1,
                'urgency': 4.9,
            }]})

        # TEST CLOSED ISSUE.
        db.synchronize(iter(()), bwconfig, 'general')

        completed_tasks = tw.load_tasks()

        tasks = remove_non_deterministic_keys(copy.deepcopy(completed_tasks))
        del tasks['completed'][0]['end']
        self.assertEqual(tasks, {
            'completed': [{
                'project': 'sample_project',
                'description': 'Yada yada yada.',
                'githubtype': 'issue',
                'githuburl': 'https://example.com',
                'id': 0,
                'priority': 'M',
                'status': 'completed',
                'urgency': 4.9,
            }],
            'pending': []})

        # TEST REOPENED ISSUE
        db.synchronize(iter((issue,)), bwconfig, 'general')

        tasks = tw.load_tasks()
        self.assertEqual(
            completed_tasks['completed'][0]['uuid'],
            tasks['pending'][0]['uuid'])

        tasks = remove_non_deterministic_keys(tasks)
        self.assertEqual(tasks, {
            'completed': [],
            'pending': [{
                'priority': 'M',
                'project': 'sample_project',
                'status': 'pending',
                'description': 'Yada yada yada.',
                'githuburl': 'https://example.com',
                'githubtype': 'issue',
                'id': 1,
                'urgency': 4.9,
            }]})


class TestUDAs(ConfigTest):
    def test_udas(self):
        self.config = BugwarriorConfigParser()
        self.config.add_section('general')
        self.config.set('general', 'targets', 'my_service')
        self.config.add_section('my_service')
        self.config.set('my_service', 'service', 'github')
        self.config.set('my_service', 'github.login', 'ralphbean')
        self.config.set('my_service', 'github.username', 'ralphbean')
        self.config.set('my_service', 'github.password', 'abc123')
        self.config.set('my_service', 'service', 'github')

        conf = self.validate()
        udas = sorted(list(db.get_defined_udas_as_strings(conf, 'general')))
        self.assertEqual(udas, [
            'uda.githubbody.label=Github Body',
            'uda.githubbody.type=string',
            'uda.githubclosedon.label=GitHub Closed',
            'uda.githubclosedon.type=date',
            'uda.githubcreatedon.label=Github Created',
            'uda.githubcreatedon.type=date',
            'uda.githubmilestone.label=Github Milestone',
            'uda.githubmilestone.type=string',
            'uda.githubnamespace.label=Github Namespace',
            'uda.githubnamespace.type=string',
            'uda.githubnumber.label=Github Issue/PR #',
            'uda.githubnumber.type=numeric',
            'uda.githubrepo.label=Github Repo Slug',
            'uda.githubrepo.type=string',
            'uda.githubstate.label=GitHub State',
            'uda.githubstate.type=string',
            'uda.githubtitle.label=Github Title',
            'uda.githubtitle.type=string',
            'uda.githubtype.label=Github Type',
            'uda.githubtype.type=string',
            'uda.githubupdatedat.label=Github Updated',
            'uda.githubupdatedat.type=date',
            'uda.githuburl.label=Github URL',
            'uda.githuburl.type=string',
            'uda.githubuser.label=Github User',
            'uda.githubuser.type=string',
        ])
