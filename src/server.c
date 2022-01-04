// 
// server.c: A very, very simple web server
//
// To run:
//  ./server <portnum (above 2000)>
//
// Repeatedly handles HTTP requests sent to this port number.
// Most of the work is done within routines written in request.c
//

#include "segel.h"
#include "request.h"
#include "queue.h"

/** MACRO MIN(a,b):
 *  Return the minimum of a,b */
#define MIN(a,b) (((a) < (b)) ? (a) : (b))

/** MACRO CIEL(x):
 *  Return x, rounded up */
#define CIEL(x) (((double)((int)(x) == (x))) ? (int)(x) : (x) + 1)

/** __TOSCHEDALG(ADDR, STR):
 *  Convert thr string STR to enum schedalg*/
#define __TOSCHEDALG(ADDR, STR)         \
    if (!strcmp(STR, "block"))          \
        *ADDR = BLOCK;                  \
    else if (!strcmp(STR, "dt"))        \
        *ADDR = DT;                     \
    else if (!strcmp(STR, "dh"))        \
        *ADDR = DH;                     \
    else if (!strcmp(STR, "random"))    \
        *ADDR = RANDOM;                 \
    else                                \
        *ADDR = SCHEDALG_ERROR;         \

/** ENUM schedalg(10,11,12,13,14): 
 *  Used for replacing the string representing the overloading argument */
typedef enum 
{
    BLOCK = 10,
    DT,
    DH,
    RANDOM,
    SCHEDALG_ERROR
} schedalg;

/** STRUCT ThrdArgs: 
 *  Used for passing argument to the running threads */
typedef struct arg_struct 
{
    Queue thrd_queue;
    Queue wait_queue;
    int max_thrd_queue_size;
    int max_wait_queue_size;
    int id;
} ThrdArgs;

/** MUTEX mutex:
 *  Global mutex used for locking all critical code */
pthread_mutex_t mutex;

/** COND mainthread_cond:
 *  Global cond used for locking the mutex from the main thread */
pthread_cond_t mainthread_cond;

/** COND workerthread_cond:
 *  Global cond used for locking the mutex from the working threads */
pthread_cond_t workerthread_cond;

/** COND_VAR curr_thrd_queue_size: 
 *  Global cond variable representing the size of the threads currently working on a request */
int curr_thrd_queue_size = 0;

/** COND_VAR curr_wait_queue_size: 
 *  Global cond variable representing the size of the requests currently waitnig for thread */
int curr_wait_queue_size = 0;
                                
/** THREAD_FUNC runThread: 
 *  thread function used for running a request-handeling thread
 *  Arguments: 
 *      @ void* args - struct ThrdArgs casted to void* */
void* runThread(void* args)
{
    ThrdArgs* thrd_args = (ThrdArgs*)args;
    Stats thrd_stats;
    initStats(&thrd_stats, thrd_args->id);
    while (1)
    {
        pthread_mutex_lock(&mutex);
        while (curr_wait_queue_size == 0)
        {
            pthread_cond_wait(&workerthread_cond, &mutex);
        }

        ConnVar conn = queueFront(thrd_args->wait_queue);
        queueDequeue(thrd_args->wait_queue);
        curr_wait_queue_size--;
        curr_thrd_queue_size++;
        gettimeofday(&(conn->dispatch_time), NULL);
        pthread_mutex_unlock(&mutex);
    
        requestHandle(conn, &thrd_stats);
        Close(conn->connfd);
        free(conn);

        pthread_mutex_lock(&mutex);
        curr_thrd_queue_size--;
        pthread_cond_signal(&mainthread_cond);
        pthread_mutex_unlock(&mutex);
    }
    pthread_exit(NULL);
    return NULL;
}


/** FUNC getArgs: 
 *  parsing the server arguments to the given pointers
 *  Arguments: 
 *      @ int *port                 - pointer to port of the server 
 *      @ int *threads              - pointer to the number of threads
 *      @ int *queue_size           - pointer to the maximum number of requests
 *      @ schedalg* overloading_opt - pointer to the overloading method
 *      @ int argc                  - number of argument given to main
 *      @ char *argv[]              - argument vector given to main
 * */
void getArgs(int *port, int *threads, int* queue_size, schedalg* overloading_opt, int argc, char *argv[])
{
    if (argc < 5) 
    {
	    fprintf(stderr, "Usage: %s <port> <threads> <queue_size> <schedalg>\n", argv[0]);
	    exit(1);
    }
    *port = atoi(argv[1]);
    *threads = atoi(argv[2]);
    *queue_size = atoi(argv[3]);
    __TOSCHEDALG(overloading_opt, argv[4]);
}


int main(int argc, char *argv[])
{
    // initialize the global mutex and conds
    pthread_mutex_init(&mutex, NULL);
    pthread_cond_init(&mainthread_cond, NULL);
    pthread_cond_init(&workerthread_cond, NULL);

    int listenfd, connfd, port, threads, queue_size, clientlen;
    schedalg overloading_opt;
    struct sockaddr_in clientaddr;

    // parse the arguments into the pointers above
    getArgs(&port, &threads, &queue_size, &overloading_opt, argc, argv);

    // running threads queue - though not being used as queue
    Queue thrd_queue = queueCreate(threads);        
    // waiting for queue
    Queue wait_queue = queueCreate(queue_size);     

    pthread_t* thrd = (pthread_t*)malloc(threads*sizeof(*thrd));
    ThrdArgs* targs = (ThrdArgs*)malloc(threads*sizeof(*targs));

    if (!thrd || !targs) 
    {
        // In a perfect world, I would have actually do something here #1
        return 0;
    }

    for(int i = 0; i < threads; i++)
    {
        targs[i].thrd_queue = thrd_queue;
        targs[i].wait_queue = wait_queue;
        targs[i].max_wait_queue_size = queue_size;
        targs[i].max_thrd_queue_size = threads;
        targs[i].id = i;
        pthread_create(&thrd[i], NULL, runThread, (void*)&targs[i]);
    }

    listenfd = Open_listenfd(port);
    while (1) 
    {
    	clientlen = sizeof(clientaddr);
    	connfd = Accept(listenfd, (SA *)&clientaddr, (socklen_t *) &clientlen);
        ConnVar new_conn = (ConnVar)malloc(sizeof(*new_conn));
        if (!new_conn)
        {
            // In a perfect world, I would have actually do something here #2
            return 0;
        }
        new_conn->connfd = connfd;
        gettimeofday(&(new_conn->arrive_time), NULL);

        /* CRITICAL CODE - start */
        pthread_mutex_lock(&mutex);
        // all threads occupied and reached the max request - ignore new requests
        if (curr_thrd_queue_size == queue_size)
        {
            Close(connfd);
            free(new_conn);
        } 
        // Max number of requests in the server (working or waiting) - use overloading method
        else if (curr_wait_queue_size + curr_thrd_queue_size >= queue_size && curr_wait_queue_size != 0)
        {
            int num_to_drop;
            ConnVar del;
            switch (overloading_opt)
            {
                // Block Overloadnig Method - Block the main thread (not busy wait) until space become available
                case BLOCK:
                    while (curr_wait_queue_size + curr_thrd_queue_size >= queue_size)
                    {
                        pthread_cond_wait(&mainthread_cond, &mutex);
                    }
                    queueEnqueue(wait_queue, new_conn);
                    curr_wait_queue_size++;
                    break;

                // Drop-Tail Overloadnig Method - Ignore new request until space become available
                case DT:
                    Close(new_conn->connfd);
                    free(new_conn);
                    break;

                // Drop-Head Overloadnig Method - Drop the oldest request on waiting,
                // and insert the new request
                case DH:
                    del = queueFront(wait_queue);
                    queueDequeue(wait_queue);
                    Close(del->connfd);
                    free(del);
                    queueEnqueue(wait_queue, new_conn);
                    break;
                
                // Random Overloadnig Method - Drop half of the requests in the server (on waiting)
                case RANDOM:
                	// opt1
                    // num_to_drop = MIN(curr_wait_queue_size, CIEL((double)(curr_wait_queue_size+curr_thrd_queue_size)/2));
                	// opt2
                	num_to_drop = CIEL((double)(curr_wait_queue_size)/2);
                    while(num_to_drop > 0)
                    {
                        del = queueFront(wait_queue);
                        queueDequeue(wait_queue);
                        Close(del->connfd);
                        free(del);
                        curr_wait_queue_size--;
                        num_to_drop--;
                    }
                    queueEnqueue(wait_queue, new_conn);
                    curr_wait_queue_size++;
                    break;
                
                // Should not reach here
                case SCHEDALG_ERROR:
                    Close(new_conn->connfd);
                    free(new_conn);
                    break;
            }
        }
        // All good - Regulary insert the request
        else 
        {
            queueEnqueue(wait_queue, new_conn);
            curr_wait_queue_size++;
        }
        // Send wakeup signal for all the working threads
        pthread_cond_broadcast(&workerthread_cond);
        pthread_mutex_unlock(&mutex);
        /* CRITICAL CODE - start */
    }
    // Although never reach here - Free all resources  
    queueDestroy(wait_queue);
    queueDestroy(thrd_queue);
    free(thrd);
    free(targs);
    pthread_mutex_destroy(&mutex);
    pthread_cond_destroy(&mainthread_cond);
    pthread_cond_destroy(&workerthread_cond);
    return 0;
}

