#include "console.h"
#include "file_system.h"
#include "pen.h"
#include "threads.h"

pen::window_creation_params pen_window{
    1280,           // width
    720,            // height
    4,              // MSAA samples
    "empty_project" // window title / process name
};

PEN_TRV pen::user_entry(void* params)
{
    PEN_LOG("User Thread Entry");

    // unpack the params passed to the thread and signal to the engine it ok to proceed
    pen::job_thread_params* job_params = (pen::job_thread_params*)params;
    pen::job*               p_thread_info = job_params->job_info;
    pen::semaphore_post(p_thread_info->p_sem_continue, 1);

    for (;;)
    {
        PEN_LOG("User Thread Update");

        pen::thread_sleep_us(16000);

        // msg from the engine we want to terminate
        if (pen::semaphore_try_wait(p_thread_info->p_sem_exit))
        {
            break;
        }
    }

    // signal to the engine the thread has finished
    pen::semaphore_post(p_thread_info->p_sem_terminated, 1);

    return PEN_THREAD_OK;
}