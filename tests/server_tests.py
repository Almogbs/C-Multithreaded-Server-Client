import math
import os
import time
import unittest
import subprocess as sp
import asyncio
import requests_async as requests
from h11 import RemoteProtocolError

SERVER_PATH = os.path.realpath(os.path.join(os.path.curdir, '..', 'server'))
DYNAMIC_REQ_TIME = 0.2
DEFAULT_PORT = 8080
DEFAULT_THREAD_COUNT = 3
DEFAULT_QUEUE_SIZE = 7
DEFAULT_STATIC_PAGE = 'home.html'
DEFAULT_DYNAMIC_PAGE = 'output.cgi'


class RequestResult:
    def __init__(self, req_ind, res=None, e=None):
        self.res = res
        self.e = e
        self.req_ind = req_ind

    def has_exception(self):
        return self.e is not None

    def is_exception_of_type(self, exc_type):
        return isinstance(self.e, exc_type)


class RequestsTest(unittest.TestCase):
    def __init__(self, *args, queue_size=DEFAULT_QUEUE_SIZE, thread_count=DEFAULT_THREAD_COUNT, policy='dt', **kwargs):
        super().__init__(*args, **kwargs)
        self.dyn_url = f'http://localhost:{DEFAULT_PORT}/{DEFAULT_DYNAMIC_PAGE}'
        self.static_url = f'http://localhost:{DEFAULT_PORT}/{DEFAULT_STATIC_PAGE}'
        self.not_found_url = f'http://localhost:{DEFAULT_PORT}/not_found'
        self.forbidden_url = f'http://localhost:{DEFAULT_PORT}/forbidden.cgi'
        self.queue_size = queue_size
        self.max_reqs = self.queue_size
        self.server_path = SERVER_PATH
        self.thread_count = thread_count
        self.policy = policy
        if policy == 'random':
            self.per_drop_size = int(0.5 * self.queue_size)
        elif policy in ['dt', 'dh']:
            self.per_drop_size = 1
        elif policy == 'block':
            self.per_drop_size = 0

        self.last_req_index = 0

    def setUp(self):
        print('Setting up test:')
        print(f'\tthread: {self.thread_count}')
        print(f'\tqueue size: {self.queue_size}')
        print(f'\tpolicy: {self.policy}')
        os.chdir(os.path.dirname(self.server_path))
        self.server = sp.Popen([self.server_path, f'{DEFAULT_PORT}', f'{self.thread_count}', f'{self.queue_size}', self.policy])
        # input('Confirm open port and hit RETURN')
        # print('')

    def tearDown(self) -> None:
        self.server.terminate()

    async def make_req(self, url, method='get'):
        try:
            # arrival_time = time.time() * 1000  # in milliseconds
            req_ind = self.last_req_index
            self.last_req_index += 1
            if method == 'get':
                response = await requests.get(url)
            elif method == 'post':
                response = await requests.post(url)
            elif method == 'delete':
                response = await requests.delete(url)
            else:
                self.fail('Unknown request method')

            # response_time = time.time() * 1000
            # self.assertAlmostEqual(arrival_time, float(response.headers['stat-req-arrival']), delta=min(500 * DYNAMIC_REQ_TIME, (response_time - arrival_time) * 0.2))
        except Exception as e:
            r = RequestResult(req_ind=req_ind, e=e)
            return r
        else:
            r = RequestResult(req_ind=req_ind, res=response)
            return r

    async def make_requests(self, url, total_reqs):
        print(f'Requesting url: {self.dyn_url}')
        self.last_req_index = 0
        tasks = []
        fail_expected_tasks = []
        thread_stats = [{'count': 0, 'dyn': 0, 'static': 0} for _ in range(self.thread_count)]
        expected_error_count = total_reqs - self.max_reqs + ((-(total_reqs - self.max_reqs)) % self.per_drop_size)
        expected_average_dispatch =  DYNAMIC_REQ_TIME * (float(total_reqs - expected_error_count) / self.thread_count) / 2
        if self.policy == 'random':
            for _ in range(total_reqs):
                task = asyncio.ensure_future(self.make_req(url))
                tasks.append(task)
        elif self.policy == 'dt':
            for _ in range(total_reqs - expected_error_count):
                task = asyncio.ensure_future(self.make_req(url))
                tasks.append(task)

            for _ in range(expected_error_count):
                task = asyncio.ensure_future(self.make_req(url))
                fail_expected_tasks.append(task)

        elif self.policy == 'dh':
            for _ in range(expected_error_count):
                task = asyncio.ensure_future(self.make_req(url))
                fail_expected_tasks.append(task)

            for _ in range(total_reqs - expected_error_count):
                task = asyncio.ensure_future(self.make_req(url))
                tasks.append(task)

        responses = await asyncio.gather(*tasks, *fail_expected_tasks, return_exceptions=True)

        responses = sorted(responses, key=lambda x: x.req_ind)

        error_count = 0
        total_dispatch = 0
        for res in responses:
            if res.is_exception_of_type(RemoteProtocolError):
                error_count += 1
                continue
            elif res.has_exception():
                raise res.e

            res = res.res
            total_dispatch += float(res.headers['stat-req-dispatch'].replace(": ",''))
            count, dyn, static = int(float(res.headers['stat-thread-count'].replace(": ",''))), int(float(res.headers['stat-thread-dynamic'].replace(": ",''))), int(float(res.headers['stat-thread-static'].replace(": ",'')))

            tid = int(float(res.headers['stat-thread-id'].replace(": ",'')))
            thread_stats[tid]['count'] = max(count, thread_stats[tid]['count'])
            thread_stats[tid]['dyn'] = max(dyn, thread_stats[tid]['dyn'])
            thread_stats[tid]['static'] = max(static, thread_stats[tid]['static'])
            self.assertEqual(count, dyn)
            self.assertEqual(static, 0)
            # self.assertAlmostEqual(float(res.headers['stat-req-arrival']), arrival_time)

        average_dispatch = total_dispatch / float(total_reqs - error_count)
        #self.assertAlmostEqual(average_dispatch, expected_average_dispatch, delta=expected_average_dispatch * 0.3,
        #                       msg=f'Unexpected average dispatch time. Expected: {expected_average_dispatch}. Actual: {average_dispatch}')
        total_count = total_dyn = 0

        for stat in thread_stats:
            total_count += stat['count']
            total_dyn += stat['dyn']


        print(f'Requests succeeded: {total_count}')
        print(f'Requests failed: {error_count}')

        self.assertEqual(total_count, total_reqs - error_count)
        self.assertEqual(total_count, total_dyn)

        self.assertEqual(error_count, expected_error_count, f'Unexpected error count. Expected {expected_error_count}. Actual: {error_count}')

        # TODO: Fix check. Should check that the correct requests failed for each policy type
        # if self.policy == 'dh':
        #     for res in responses[self.thread_count:self.thread_count + error_count]:
        #         self.assertIsInstance(res.e, RemoteProtocolError)
        # elif self.policy == 'dt':
        #     for res in responses[-error_count:]:
        #         self.assertIsInstance(res.e, RemoteProtocolError)


class TestDropTailRequests(RequestsTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, policy='dt', **kwargs)

    def test_drop_single(self):
        asyncio.run(self.make_requests(self.dyn_url, self.max_reqs + 1))

    def test_drop_double_queue_size(self):
        asyncio.run(self.make_requests(self.dyn_url, self.max_reqs + self.queue_size * 2))


class TestDropHeadRequests(RequestsTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, policy='dh', **kwargs)

    def test_drop_single(self):
        asyncio.run(self.make_requests(self.dyn_url, self.max_reqs + 1))

    def test_drop_double_queue_size(self):
        asyncio.run(self.make_requests(self.dyn_url, self.max_reqs + self.queue_size * 2))


class TestDropRandomRequests(RequestsTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, queue_size=16, policy='random', **kwargs)

    def test_single_drop_random(self):
        asyncio.run(self.make_requests(self.dyn_url, self.max_reqs + 1))

    def test_double_drop_random(self):
        asyncio.run(self.make_requests(self.dyn_url, self.max_reqs + 2 * int(0.5 * self.queue_size)))

    def test_no_drop(self):
        asyncio.run(self.make_requests(self.dyn_url, self.max_reqs))


class TestMultiThreaded(RequestsTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, queue_size=80, **kwargs)

    def test_time_full_queue(self):
        start_time = time.time()
        req_count = self.max_reqs
        asyncio.run(self.make_requests(self.dyn_url, req_count))
        run_time = time.time() - start_time
        expected_runtime = math.ceil(req_count / float(self.thread_count)) * DYNAMIC_REQ_TIME
        # This is optimal so it must be greater
        self.assertGreater(run_time, expected_runtime)
        self.assertLess(run_time, expected_runtime * 2)

    def test_better_with_more_threads(self):
        start_time = time.time()
        req_count = self.max_reqs
        asyncio.run(self.make_requests(self.dyn_url, req_count))
        few_threads_run_time = time.time() - start_time

        self.server.terminate()
        self.thread_count *= 3
        self.setUp()

        start_time = time.time()
        asyncio.run(self.make_requests(self.dyn_url, req_count))
        more_threads_run_time = time.time() - start_time

        self.assertTrue(2 * more_threads_run_time < few_threads_run_time < 3 * more_threads_run_time, "Performance doesn't scale as expected with amount of threads")


class TestStatusCodes(RequestsTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, thread_count=1, queue_size=1, **kwargs)

    async def _make_req(self, url, expected_status, stat_map, method='get'):
        task = asyncio.ensure_future(self.make_req(url, method=method))

        res = await asyncio.ensure_future(task)

        headers = res.res.headers

        for k in stat_map:
            self.assertIn(k, headers)
            if stat_map[k] is not None:
                self.assertEqual(int(float(headers[k].replace(": ",''))), stat_map[k], f'Unexpected value for {k}. Expected: {stat_map[k]}. Actual: {headers[k]}')

        self.assertEqual(expected_status, res.res.status_code, f'Unexpected status code. Expected: {expected_status}. Actual: {res.res.status_code}')

    def test_404(self):
        stat_map = {
            'stat-req-arrival': None,
            'stat-req-dispatch': 0,
            'stat-thread-id': 0,
            'stat-thread-count': 1,
            'stat-thread-static': 0,
            'stat-thread-dynamic': 0
        }

        asyncio.run(self._make_req(self.not_found_url, 404, stat_map))

    def test_dynamic(self):
        stat_map = {
            'stat-req-arrival': None,
            'stat-req-dispatch': 0,
            'stat-thread-id': 0,
            'stat-thread-count': 1,
            'stat-thread-static': 0,
            'stat-thread-dynamic': 1
        }
        asyncio.run(self._make_req(self.dyn_url, 200, stat_map))

    def test_static(self):
        stat_map = {
            'stat-req-arrival': None,
            'stat-req-dispatch': 0,
            'stat-thread-id': 0,
            'stat-thread-count': 1,
            'stat-thread-static': 1,
            'stat-thread-dynamic': 0
        }
        asyncio.run(self._make_req(self.static_url, 200, stat_map))

    def test_forbidden(self):
        stat_map = {
            'stat-req-arrival': None,
            'stat-req-dispatch': 0,
            'stat-thread-id': 0,
            'stat-thread-count': 1,
            'stat-thread-static': 0,
            'stat-thread-dynamic': 0
        }
        asyncio.run(self._make_req(self.forbidden_url, 403, stat_map))

    def test_post(self):
        stat_map = {
            'stat-req-arrival': None,
            'stat-req-dispatch': 0,
            'stat-thread-id': 0,
            'stat-thread-count': 1,
            'stat-thread-static': 0,
            'stat-thread-dynamic': 0
        }
        asyncio.run(self._make_req(self.static_url, 501, stat_map, method='post'))


if __name__ == '__main__':
    unittest.main()
