#include "pen.h"
#include "threads.h"
#include "memory.h"
#include "renderer.h"
#include "timer.h"
#include "file_system.h"
#include "pen_string.h"
#include "loader.h"
#include "pmfx.h"

using namespace put;

pen::window_creation_params pen_window
{
    1280,					//width
    720,					//height
    4,						//MSAA samples
    "textures"		        //window title / process name
};

typedef struct vertex
{
    float x, y, z, w;
} vertex;

typedef struct textured_vertex
{
    float x, y, z, w;
    float u, v;
} textured_vertex;

PEN_THREAD_RETURN pen::game_entry( void* params )
{
    //unpack the params passed to the thread and signal to the engine it ok to proceed
    pen::job_thread_params* job_params = (pen::job_thread_params*)params;
    pen::job_thread* p_thread_info = job_params->job_thread_info;
    pen::threads_semaphore_signal(p_thread_info->p_sem_continue, 1);
    
    //create 2 clear states one for the render target and one for the main screen, so we can see the difference
    static pen::clear_state cs =
    {
        0.0f, 0.0, 1.0f, 1.0f, 1.0f, 0x00, PEN_CLEAR_COLOUR_BUFFER | PEN_CLEAR_DEPTH_BUFFER,
    };

    u32 clear_state = pen::renderer_create_clear_state( cs );

    //raster state
    pen::rasteriser_state_creation_params rcp;
    pen::memory_zero( &rcp, sizeof( rasteriser_state_creation_params ) );
    rcp.fill_mode = PEN_FILL_SOLID;
    rcp.cull_mode = PEN_CULL_NONE;
    rcp.depth_bias_clamp = 0.0f;
    rcp.sloped_scale_depth_bias = 0.0f;

    u32 raster_state = pen::renderer_create_rasterizer_state( rcp );

    //viewport
    pen::viewport vp =
    {
        0.0f, 0.0f,
        1280.0f, 720.0f,
        0.0f, 1.0f
    };

    //load shaders now requiring dependency on pmfx to make loading simpler.
    pmfx::pmfx_handle textured_shader = pmfx::load("textured");
    
    u32 test_texture = put::load_texture("data/textures/test_normal.dds");

    //create vertex buffer for a quad
    textured_vertex quad_vertices[] =
    {
        -0.5f, -0.5f, 0.5f, 1.0f,       //p1
        0.0f, 0.0f,                     //uv1

        -0.5f, 0.5f, 0.5f, 1.0f,        //p2 
        0.0f, 1.0f,                     //uv2     

        0.5f, 0.5f, 0.5f, 1.0f,         //p3
        1.0f, 1.0f,                     //uv3

        0.5f, -0.5f, 0.5f, 1.0f,        //p4
        1.0f, 0.0f,                     //uv4
    };

    pen::buffer_creation_params bcp;
    bcp.usage_flags = PEN_USAGE_DEFAULT;
    bcp.bind_flags = PEN_BIND_VERTEX_BUFFER;
    bcp.cpu_access_flags = 0;

    bcp.buffer_size = sizeof( textured_vertex ) * 4;
    bcp.data = ( void* ) &quad_vertices[ 0 ];

    u32 quad_vertex_buffer = pen::renderer_create_buffer( bcp );

    //create index buffer
    u16 indices[] =
    {
        0, 1, 2,
        2, 3, 0
    };

    bcp.usage_flags = PEN_USAGE_IMMUTABLE;
    bcp.bind_flags = PEN_BIND_INDEX_BUFFER;
    bcp.cpu_access_flags = 0;
    bcp.buffer_size = sizeof( u16 ) * 6;
    bcp.data = ( void* ) &indices[ 0 ];

    u32 quad_index_buffer = pen::renderer_create_buffer( bcp );

    //create a sampler object so we can sample a texture
    pen::sampler_creation_params scp;
    pen::memory_zero( &scp, sizeof( pen::sampler_creation_params ) );
    scp.filter = PEN_FILTER_MIN_MAG_MIP_LINEAR;
    scp.address_u = PEN_TEXTURE_ADDRESS_CLAMP;
    scp.address_v = PEN_TEXTURE_ADDRESS_CLAMP;
    scp.address_w = PEN_TEXTURE_ADDRESS_CLAMP;
    scp.comparison_func = PEN_COMPARISON_ALWAYS;
    scp.min_lod = 0.0f;
    scp.max_lod = 4.0f;

    u32 linear_sampler = pen::renderer_create_sampler( scp );

    while( 1 )
    {
        pen::renderer_set_rasterizer_state( raster_state );

        //bind back buffer and clear
        pen::renderer_set_viewport( vp );
        pen::renderer_set_targets( PEN_BACK_BUFFER_COLOUR, PEN_BACK_BUFFER_DEPTH );
        pen::renderer_clear( clear_state );

        //draw quad
        {
            //bind vertex layout and shaders
            pmfx::set_technique(textured_shader, 0);

            //bind vertex buffer
            u32 stride = sizeof( textured_vertex );
            pen::renderer_set_vertex_buffer( quad_vertex_buffer, 0, stride, 0 );
            pen::renderer_set_index_buffer( quad_index_buffer, PEN_FORMAT_R16_UINT, 0 );

            //bind render target as texture on sampler 0
            pen::renderer_set_texture( test_texture, linear_sampler, 0, PEN_SHADER_TYPE_PS );

            //draw
            pen::renderer_draw_indexed( 6, 0, 0, PEN_PT_TRIANGLELIST );
        }

        //present 
        pen::renderer_present();

        pen::renderer_consume_cmd_buffer();

        //msg from the engine we want to terminate
        if( pen::threads_semaphore_try_wait( p_thread_info->p_sem_exit ) )
        {
            break;
        }
    }
    
    //clean up mem here
    pmfx::release( textured_shader );
    
    pen::renderer_release_buffer(quad_vertex_buffer);
    pen::renderer_release_buffer(quad_index_buffer);
    pen::renderer_release_sampler(linear_sampler);
    pen::renderer_release_texture(test_texture);
    pen::renderer_consume_cmd_buffer();
    
    //signal to the engine the thread has finished
    pen::threads_semaphore_signal( p_thread_info->p_sem_terminated, 1);
    

    return PEN_THREAD_OK;
}