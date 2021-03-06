import os
import subprocess
import os.path
import re
import sys
import json
import math
import time
import dependencies
import util

# setup paths and platforms
stats_start = time.time()

shader_sub_platform = ""
shader_platform = "hlsl"
os_platform = util.get_platform_name()
system_platform = os_platform

if os_platform == "osx" or os_platform == "linux":
    shader_platform = "glsl"

for i in range(1, len(sys.argv)):
    if "-root_dir" in sys.argv[i]:
        os.chdir(sys.argv[i+1])
    if "-shader_platform" in sys.argv[i]:
        shader_platform = sys.argv[i+1]
    if "-platform" in sys.argv[i]:
        os_platform = sys.argv[i+1]

if os_platform == "ios":
    shader_sub_platform = "gles"

root_dir = os.getcwd()
config = open("build_config.json")
build_config = json.loads(config.read())
pmtech_dir = util.correct_path(build_config["pmtech_dir"])
tools_dir = os.path.join(pmtech_dir, "tools")

if system_platform == "win32":
    compiler_dir = os.path.join(pmtech_dir, "tools", "bin", "fxc")
elif system_platform == "osx":
    compiler_dir = os.path.join(pmtech_dir, "tools", "bin", "glsl")
else:
    compiler_dir = ""

temp_dir = os.path.join(root_dir, "temp")
this_file = os.path.join(tools_dir, "build_scripts", "build_shaders.py")
macros_file = os.path.join(tools_dir, "_shader_macros.h")
shader_source_dir = os.path.join(root_dir, "assets", "shaders")
pmtech_shaders = os.path.join(pmtech_dir, "assets", "shaders")
shader_build_dir = os.path.join(root_dir, "bin", os_platform, "data", "pmfx", shader_platform)

# create dirs
if not os.path.exists(shader_build_dir):
    os.makedirs(shader_build_dir)

if not os.path.exists(temp_dir):
    os.mkdir(temp_dir)

technique_texture = []

print("--------------------------------------------------------------------------------")
print("pmfx shader compilation --------------------------------------------------------")
print("--------------------------------------------------------------------------------")
print("compiling directory: " + shader_source_dir)
if os_platform == "win32":
    print("fx compiler directory :" + compiler_dir)


def us(v):
    if v == -1:
        return sys.maxsize
    return v


def parse_and_split_block(code_block):
    start = code_block.find("{") + 1
    end = code_block.find("};")
    block_conditioned = code_block[start:end].replace(";", "")
    block_conditioned = block_conditioned.replace(":", "")
    block_conditioned = block_conditioned.replace("(", "")
    block_conditioned = block_conditioned.replace(")", "")
    block_conditioned = block_conditioned.replace(",", "")
    return block_conditioned.split()


def make_input_info(inputs):
    semantic_info = [
        ["SV_POSITION", "4"],
        ["POSITION", "4"],
        ["TEXCOORD", "4"],
        ["NORMAL", "4"],
        ["TANGENT", "4"],
        ["BITANGENT", "4"],
        ["COLOR", "1"],
        ["BLENDINDICES", "1"]
    ]
    type_info = ["int", "uint", "float", "double"]
    input_desc = []
    inputs_split = parse_and_split_block(inputs)
    offset = int(0)
    for i in range(0, len(inputs_split), 3):
        num_elements = 1
        element_size = 1
        for type in type_info:
            if inputs_split[i].find(type) != -1:
                str_num = inputs_split[i].replace(type, "")
                if str_num != "":
                    num_elements = int(str_num)
        for sem in semantic_info:
            if inputs_split[i+2].find(sem[0]) != -1:
                semantic_id = semantic_info.index(sem)
                semantic_name = sem[0]
                semantic_index = inputs_split[i+2].replace(semantic_name, "")
                if semantic_index == "":
                    semantic_index = "0"
                element_size = sem[1]
                break
        size = int(element_size) * int(num_elements)
        input_attribute = {
            "name": inputs_split[i+1],
            "semantic_index": int(semantic_index),
            "semantic_id": int(semantic_id),
            "size": int(size),
            "element_size": int(element_size),
            "num_elements": int(num_elements),
            "offset": int(offset),
        }
        input_desc.append(input_attribute)
        offset += size
    return input_desc


def get_resource_info_filename(filename, build_dir):
    base_filename = os.path.basename(filename)
    dir_path = os.path.dirname(filename)
    info_filename = os.path.join(shader_build_dir, os.path.splitext(base_filename)[0], "info.json")
    return info_filename, base_filename, dir_path


def generate_shader_info(
        filename,
        included_files,
        techniques,
        texture_samplers,
        constant_buffers):

    info_filename, base_filename, dir_path = get_resource_info_filename(filename, shader_build_dir)
    print(info_filename)

    shader_info = dict()
    shader_info["files"] = []

    _this_file = os.path.join(root_dir, this_file)
    _macros_file = os.path.join(root_dir, macros_file)

    # special files which affect the validity of compiled shaders
    shader_info["files"].append(dependencies.create_info(_this_file))
    shader_info["files"].append(dependencies.create_info(_macros_file))

    included_files.insert(0, os.path.join(dir_path, base_filename))
    for ifile in included_files:
        full_name = os.path.join(root_dir, ifile)
        shader_info["files"].append(dependencies.create_info(full_name))

    shader_info["techniques"] = techniques

    shader_info["texture_samplers"] = []
    texture_samplers_split = parse_and_split_block(texture_samplers)
    i = 0
    while i < len(texture_samplers_split):
        offset = i
        tex_type = texture_samplers_split[i+0]
        if tex_type == "texture_2dms":
            data_type = texture_samplers_split[i+1]
            fragments = texture_samplers_split[i+2]
            offset = i+2
        else:
            data_type = "float4"
            fragments = 1
        sampler_desc = {
            "name": texture_samplers_split[offset+1],
            "data_type": data_type,
            "fragments": fragments,
            "type": tex_type,
            "unit": int(texture_samplers_split[offset+2])
        }
        i = offset+3
        shader_info["texture_samplers"].append(sampler_desc)

    shader_info["cbuffers"] = []
    for buffer in constant_buffers:
        buffer_decl = buffer[0:buffer.find("{")-1]
        buffer_decl_split = buffer_decl.split(":")
        buffer_name = buffer_decl_split[0].split()[1]
        buffer_loc_start = buffer_decl_split[1].find("(") + 1
        buffer_loc_end = buffer_decl_split[1].find(")", buffer_loc_start)
        buffer_reg = buffer_decl_split[1][buffer_loc_start:buffer_loc_end]
        buffer_reg = buffer_reg.strip('b')
        buffer_desc = {"name": buffer_name, "location": int(buffer_reg)}
        shader_info["cbuffers"].append(buffer_desc)

    # material cbuffer for those which need it
    buffer_desc = {"name": "material_data", "location": int(7)}
    shader_info["cbuffers"].append(buffer_desc)

    output_info = open(info_filename, 'wb+')
    output_info.write(bytes(json.dumps(shader_info, indent=4), 'UTF-8'))
    output_info.close()
    return shader_info


def compile_hlsl(source, filename, shader_model, temp_extension, entry_name, technique_name):
    global error_code
    f = os.path.basename(filename)
    f = os.path.splitext(f)[0]
    temp_file_name = os.path.join(temp_dir, f)

    if not os.path.exists(temp_file_name):
        os.mkdir(temp_file_name)

    temp_file_name = os.path.join(temp_file_name, technique_name + temp_extension )

    output_path = os.path.join(shader_build_dir, f)
    output_file_and_path = os.path.join(output_path, technique_name + temp_extension + "c")

    compiler_exe_path = os.path.join(compiler_dir,"fxc")

    temp_shader_source = open(temp_file_name, "w")
    temp_shader_source.write(source)
    temp_shader_source.close()

    cmdline = compiler_exe_path + " /T " + shader_model + " /Fo " + output_file_and_path + " " + temp_file_name
    cmdline += " /E " + entry_name
    subprocess.call(cmdline, shell=True)

def replace_io_tokens(text):
    token_io = ["input", "output"]
    token_io_replace = ["_input", "_output"]
    token_post_delimiters = ['.', ';', ' ', '(', ')', ',', '-', '+', '*', '/']
    token_pre_delimiters = [' ', '\t', '\n', '(', ')', ',', '-', '+', '*', '/']
    split = text.split(' ')
    split_replace = []
    for token in split:
        for i in range(0, len(token_io)):
            if token_io[i] in token:
                last_char = len(token_io[i])
                first_char = token.find(token_io[i])
                t = token[first_char:first_char+last_char+1]
                l = len(t)
                if first_char > 0 and token[first_char-1] not in token_pre_delimiters:
                    continue
                if l > last_char:
                    c = t[last_char]
                    if c in token_post_delimiters:
                        token = token.replace(token_io[i], token_io_replace[i])
                        continue
                elif l == last_char:
                    token = token.replace(token_io[i], token_io_replace[i])
                    continue
        split_replace.append(token)

    replaced_text = ""
    for token in split_replace:
        replaced_text += token + " "

    return replaced_text


def find_struct(shader_text, decl):
    delimiters = [" ", "\n", "{"]
    start = 0
    while True:
        start = shader_text.find(decl, start)
        if start == -1:
            return ""
        for d in delimiters:
            if shader_text[start+len(decl)] == d:
                end = shader_text.find("};", start)
                end += 2
                if start != -1 and end != -1:
                    return shader_text[start:end] + "\n\n"
                else:
                    return ""
        start += len(decl)


def find_constant_buffers(shader_text):
    cbuffer_list = []
    start = 0
    while start != -1:
        start = shader_text.find("cbuffer", start)
        if start == -1:
            break
        end = shader_text.find("};", start)
        if end != -1:
            end += 2
            cbuffer_list.append(shader_text[start:end] + "\n")
        start = end
    return cbuffer_list


def enclose_brackets(text):
    body_pos = text.find("{")
    bracket_stack = ["{"]
    text_len = len(text)
    while len(bracket_stack) > 0 and body_pos < text_len:
        body_pos += 1
        character = text[body_pos:body_pos+1]
        if character == "{":
            bracket_stack.insert(0, "{")
        if character == "}" and bracket_stack[0] == "{":
            bracket_stack.pop(0)
            body_pos += 1
    return body_pos


def find_main(shader_text, decl):
    start = shader_text.find(decl)
    if start == -1:
        return ""
    body_pos = shader_text.find("{", start)
    bracket_stack = ["{"]
    text_len = len(shader_text)
    while len(bracket_stack) > 0 and body_pos < text_len:
        body_pos += 1
        character = shader_text[body_pos:body_pos+1]
        if character == "{":
            bracket_stack.insert(0, "{")
        if character == "}" and bracket_stack[0] == "{":
            bracket_stack.pop(0)
            body_pos += 1
    return shader_text[start:body_pos] + "\n\n"


def find_struct_declarations(shader_text):
    special_structs = ["vs_input", "vs_output", "ps_input", "ps_output", "vs_instance_input"]
    struct_list = []
    start = 0
    while start != -1:
        start = shader_text.find("struct", start)
        if start == -1:
            break
        end = shader_text.find("};", start)
        if end != -1:
            end += 2
            found_struct = shader_text[start:end]
            valid = True
            for ss in special_structs:
                if ss in found_struct:
                    valid = False
            if valid:
                struct_list.append(shader_text[start:end] + "\n")
        start = end
    return struct_list


def find_generic_functions(shader_text):
    deliminator_list = [";", "\n"]
    function_list = []
    start = 0
    while 1:
        start = shader_text.find("(", start)
        if start == -1:
            break
        # make sure the { opens before any other deliminator
        deliminator_pos = shader_text.find(";", start)
        body_pos = shader_text.find("{", start)
        if deliminator_pos < body_pos:
            start = deliminator_pos
            continue
        # find the function name and return type
        function_name = shader_text.rfind(" ", 0, start)
        name_str = shader_text[function_name:start]
        if name_str.find("if:") != -1:
            start = deliminator_pos
            continue
        function_return_type = 0
        for delim in deliminator_list:
            decl_start = shader_text.rfind(delim, 0, function_name)
            if decl_start != -1:
                function_return_type = decl_start
        bracket_stack = ["{"]
        text_len = len(shader_text)
        while len(bracket_stack) > 0 and body_pos < text_len:
            body_pos += 1
            character = shader_text[body_pos:body_pos+1]
            if character == "{":
                bracket_stack.insert(0, "{")
            if character == "}" and bracket_stack[0] == "{":
                bracket_stack.pop(0)
                body_pos += 1
        function_list.append(shader_text[function_return_type:body_pos] + "\n\n")
        start = body_pos
    return function_list


def find_texture_samplers(shader_text):
    global technique_texture

    start = shader_text.find("declare_texture_samplers")
    if start == -1:
        return "\n"
    start = shader_text.find("{", start) + 1
    end = shader_text.find("};", start)
    texture_sampler_text = shader_text[start:end] + "\n"
    texture_sampler_text = texture_sampler_text.replace("\t", "")

    # add technique textures
    for alias in technique_texture:
        texture_sampler_text += str(alias[0]) + "( " + str(alias[1]) + ", " + str(alias[2]) + " );\n"

    texture_sampler_text += "\n"

    return texture_sampler_text


def clean_spaces(shader_text):
    return re.sub(' +', ' ', shader_text)


def parse_io_struct(source):
    if len(source) == 0:
        return [], []
    io_source = source
    start = io_source.find("{")
    end = io_source.find("}")
    elements = []
    semantics = []
    prev_input = start+1
    next_input = 0
    while next_input < end:
        next_input = io_source.find(";", prev_input)
        if next_input > 0:
            next_semantic = io_source.find(":", prev_input)
            elements.append(io_source[prev_input:next_semantic].strip())
            semantics.append(io_source[next_semantic+1:next_input].strip())
            prev_input = next_input + 1
        else:
            break
    # the last input will always be "};" pop it out
    elements.pop(len(elements)-1)
    semantics.pop(len(semantics)-1)
    return elements, semantics


def generate_global_io_struct(io_elements, decl):
    # global input struct for hlsl compatibility to access like input.value
    struct_source = decl
    struct_source += "\n{\n"
    for element in io_elements:
        struct_source += "\t" + element + ";\n"
    struct_source += "};\n"
    struct_source += "\n"
    return struct_source


def generate_input_assignment(io_elements, decl, local_var, suffix):
    assign_source = "\t//assign " + decl + " struct from glsl inputs\n"
    assign_source += "\t" + decl + " " + local_var + ";\n"
    for element in io_elements:
        if element.split()[1] == "position" and "vs_output" in decl:
            continue
        assign_source += "\t"
        var_name = element.split()[1]
        assign_source += local_var + "." + var_name + " = " + var_name + suffix + ";\n"
    return assign_source


def generate_output_assignment(io_elements, local_var, suffix):
    assign_source = "\n\t//assign glsl global outputs from structs\n"
    for element in io_elements:
        assign_source += "\t"
        var_name = element.split()[1]
        if var_name == "position":
           assign_source += "gl_Position = " + local_var + "." + var_name + ";\n"
        else:
            assign_source += var_name + suffix + " = " + local_var + "." + var_name + ";\n"
    return assign_source


def get_preamble():
    insert = ""
    if shader_sub_platform == "gles":
        insert += "#version 300 es\n"
        insert += "#define GLSL\n"
        insert += "#define GLES\n"
        insert += "precision highp float;\n"
    elif shader_platform == "glsl":
        insert += "#version 330 core\n"
        insert += "#define GLSL\n"
    return insert


def generate_glsl(
        source_filename, macros,
        vs_main, ps_main,
        vs_functions, ps_functions,
        vs_input_source, instance_input_source,
        vs_output_source, ps_output_source,
        constant_buffers,
        texture_samplers_source,
        technique_name,
        permutation):
    shader_name = os.path.basename(source_filename)
    shader_name = os.path.splitext(shader_name)[0]

    # parse input block
    vs_inputs, vs_input_semantics = parse_io_struct(vs_input_source)
    vs_outputs, vs_output_semantics = parse_io_struct(vs_output_source)
    instance_inputs, instance_input_semantics = parse_io_struct(instance_input_source)

    vs_input_struct_name = vs_input_source.split()[1]
    vs_output_struct_name = vs_output_source.split()[1]

    instanced = len(instance_input_source) > 0

    instance_input_struct_name = ""
    if instanced:
        instance_input_struct_name = instance_input_source.split()[1]

    ps_output_struct_name = ""

    if len(ps_output_source.split()) > 0:
        ps_output_struct_name = ps_output_source.split()[1]

    # cbuffers to uniform
    uniform_buffers = ""
    for cbuf in constant_buffers:
        name_start = cbuf.find(" ")
        name_end = cbuf.find(":")
        index_start = cbuf.find("(", name_end) + 1
        index_end = cbuf.find(")", index_start)
        uniform_buf = "layout (std140) uniform"
        uniform_buf += cbuf[name_start:name_end]
        body_start = cbuf.find("{")
        body_end = cbuf.find("};") + 2
        uniform_buf += "\n"
        uniform_buf += cbuf[body_start:body_end] + "\n"
        uniform_buffers += uniform_buf + "\n"

    # start making vs shader code
    final_vs_source = "//" + shader_name + " " + technique_name + "\n"
    final_vs_source += get_preamble()
    final_vs_source += macros
    final_vs_source += "\n\n"

    # glsl inputs
    index_counter = 0
    for vs_input in vs_inputs:
        final_vs_source += "layout(location = " + str(index_counter) + ") in " + vs_input + "_vs_input;\n"
        index_counter += 1
    for instance_input in instance_inputs:
        final_vs_source += "layout(location = " + str(index_counter) + ") in " + instance_input + "_instance_input;\n"
        index_counter += 1
    final_vs_source += "\n"

    # vs outputs
    for vs_output in vs_outputs:
        if vs_output.split()[1] != "position":
            final_vs_source += "out " + vs_output + "_vs_output;\n"
    final_vs_source += "\n"

    final_vs_source += generate_global_io_struct(vs_inputs, "struct " + vs_input_struct_name)

    if instanced:
        final_vs_source += generate_global_io_struct(instance_inputs, "struct " + instance_input_struct_name)

    final_vs_source += generate_global_io_struct(vs_outputs, "struct " + vs_output_struct_name)
    final_vs_source += texture_samplers_source
    final_vs_source += uniform_buffers
    final_vs_source += vs_functions

    glsl_vs_main = vs_main
    skip_function_start = glsl_vs_main.find("{") + 1
    skip_function_end = glsl_vs_main.find("return")
    glsl_vs_main = glsl_vs_main[skip_function_start:skip_function_end].strip()

    vs_main_pre_assign = generate_input_assignment(vs_inputs, vs_input_struct_name, "_input", "_vs_input")

    if instanced:
        vs_main_pre_assign += "\n"
        vs_main_pre_assign += generate_input_assignment(instance_inputs, instance_input_struct_name,
                                                        "instance_input", "_instance_input")

    vs_main_post_assign = generate_output_assignment(vs_outputs, "_output", "_vs_output")

    final_vs_source += "void main()\n{\n"
    final_vs_source += vs_main_pre_assign
    final_vs_source += "\n\t//main body from " + source_filename + "\n"
    final_vs_source += "\t" + glsl_vs_main + "\n"
    final_vs_source += vs_main_post_assign
    final_vs_source += "}\n"

    final_vs_source = replace_io_tokens(final_vs_source)
    final_vs_source = evaluate_conditional_blocks(final_vs_source, permutation)

    vs_fn = os.path.join(shader_build_dir, shader_name, technique_name + ".vsc")
    vs_file = open(vs_fn, "w")
    vs_file.write(final_vs_source)
    vs_file.close()

    global error_code
    vs_fn_opt = vs_fn.replace(".vsc", ".vso")
    if compiler_dir != "":
        compiler_exe = os.path.join(compiler_dir, system_platform, "glslopt")
        cmd = compiler_exe + " -v " + vs_fn + " " + vs_fn_opt
        subprocess.call(cmd, shell=True)

    # start making ps shader code
    if ps_main != "":
        ps_outputs, ps_output_semantics = parse_io_struct(ps_output_source)

        final_ps_source = "//" + shader_name + " " + technique_name + "\n"
        final_ps_source += get_preamble()
        final_ps_source += macros
        final_ps_source += "\n\n"

        # ps inputs
        for vs_output in vs_outputs:
            if vs_output.split()[1] != "position":
                final_ps_source += "in " + vs_output + "_vs_output;\n"
        final_ps_source += "\n"

        # ps outputs
        for p in range(0, len(ps_outputs)):
            if "SV_Depth" in ps_output_semantics[p]:
                continue
            else:
                output_index = ps_output_semantics[p].replace("SV_Target", "")
                if output_index != "":
                    final_ps_source += "layout(location = " + output_index + ") "
                final_ps_source += "out " + ps_outputs[p] + "_ps_output;\n"
        final_ps_source += "\n"

        final_ps_source += generate_global_io_struct(vs_outputs, "struct " + vs_output_struct_name)

        if ps_output_struct_name != "":
            final_ps_source += generate_global_io_struct(ps_outputs, "struct " + ps_output_struct_name)
            
        final_ps_source += texture_samplers_source
        final_ps_source += uniform_buffers
        final_ps_source += ps_functions

        glsl_ps_main = ps_main
        skip_function_start = glsl_ps_main.find("{") + 1
        skip_function_end = glsl_ps_main.find("return")
        glsl_ps_main = glsl_ps_main[skip_function_start:skip_function_end].strip()

        ps_main_pre_assign = generate_input_assignment(vs_outputs, vs_output_struct_name, "_input", "_vs_output")
        ps_main_post_assign = generate_output_assignment(ps_outputs, "_output", "_ps_output")

        final_ps_source += "void main()\n{\n"
        final_ps_source += ps_main_pre_assign
        final_ps_source += "\n\t//main body from " + source_filename + "\n"
        final_ps_source += "\t" + glsl_ps_main + "\n"
        final_ps_source += ps_main_post_assign
        final_ps_source += "}\n"

        final_ps_source = replace_io_tokens(final_ps_source)
        final_ps_source = evaluate_conditional_blocks(final_ps_source, permutation)

        ps_fn = os.path.join(shader_build_dir, shader_name, technique_name + ".psc")
        ps_file = open(ps_fn, "w")
        ps_file.write(final_ps_source)
        ps_file.close()

        # optimise and check compile errors
        ps_fn_opt = ps_fn.replace(".psc", ".pso")
        if compiler_dir != "":
            compiler_exe = os.path.join(compiler_dir, system_platform, "glslopt")
            cmd = compiler_exe + " -f " + ps_fn + " " + ps_fn_opt
            ret = subprocess.call(cmd, shell=True)


def find_includes(file_text, root):
    global added_includes
    include_list = []
    start = 0
    while 1:
        start = file_text.find("#include", start)
        if start == -1:
            break
        start = file_text.find("\"", start) + 1
        end = file_text.find("\"", start)
        if start == -1 or end == -1:
            break
        include_name = file_text[start:end]
        include_path = os.path.join(root, include_name)
        include_path = util.sanitize_file_path(include_path)
        if include_path not in added_includes:
            include_list.append(include_path)
            added_includes.append(include_path)
    return include_list


def find_used_functions(entry_func, function_list):
    used_functions = [entry_func]
    added_function_names = []
    ordered_function_list = [entry_func]
    for used_func in used_functions:
        for func in function_list:
            if func == used_func:
                continue
            name = func.split(" ")[1]
            end = name.find("(")
            name = name[0:end]
            if used_func.find(name + "(") != -1:
                if name in added_function_names:
                    continue
                used_functions.append(func)
                added_function_names.append(name)
    for func in function_list:
        name = func.split(" ")[1]
        end = name.find("(")
        name = name[0:end]
        if name in added_function_names:
            ordered_function_list.append(func)
    ordered_function_list.remove(entry_func)
    used_function_source = ""
    for used_func in ordered_function_list:
        used_function_source += used_func + "\n\n"
    return used_function_source


def add_files_recursive(filename, root):
    file_path = filename
    if not os.path.exists(filename):
        file_path = os.path.join(root, filename)
    included_file = open(file_path, "r")
    shader_source = included_file.read()
    included_file.close()
    shader_source = clean_spaces(shader_source)
    sub_root = os.path.dirname(file_path)
    include_list = find_includes(shader_source, sub_root)
    for include_file in reversed(include_list):
        included_source, sub_includes = add_files_recursive(include_file, sub_root)
        shader_source = included_source + "\n" + shader_source
        include_list = include_list + sub_includes
    return shader_source, include_list


def check_dependencies(filename, included_files):
    # look for .json file
    file_list = list()
    file_list.append(dependencies.sanitize_filename(os.path.join(root_dir, filename)))
    file_list.append(dependencies.sanitize_filename(os.path.join(root_dir, this_file)))
    file_list.append(dependencies.sanitize_filename(os.path.join(root_dir, macros_file)))
    info_filename, base_filename, dir_path = get_resource_info_filename(filename, shader_build_dir)
    for f in included_files:
        file_list.append(dependencies.sanitize_filename(os.path.join(root_dir, f)))
    if os.path.exists(info_filename):
        info_file = open(info_filename, "r")
        info = json.loads(info_file.read())
        for prev_built_with_file in info["files"]:
            sanitized_name = dependencies.sanitize_filename(prev_built_with_file["name"])
            if sanitized_name in file_list:
                if not os.path.exists(sanitized_name):
                    return False
                if prev_built_with_file["timestamp"] < os.path.getmtime(sanitized_name):
                    info_file.close()
                    print(os.path.basename(sanitized_name) + " is out of date")
                    return False
            else:
                print(file_list)
                print(sanitized_name + " is not in list")
                return False
        info_file.close()
    else:
        return False
    return True


def create_shader_set(filename, root):
    global added_includes
    added_includes = []
    shader_file_text, included_files = add_files_recursive(filename, root)
    up_to_date = check_dependencies(filename, included_files)

    shader_base_name = os.path.basename(filename)
    shader_set_dir = os.path.splitext(shader_base_name)[0]
    shader_set_build_dir = os.path.join(shader_build_dir, shader_set_dir)

    if not os.path.exists(shader_set_build_dir):
        os.makedirs(shader_set_build_dir)

    if up_to_date:
        print(filename + " file up to date")
        return False, None, None

    return True, shader_file_text, included_files


def evaluate_conditional_blocks(source, permutation):
    if not permutation:
        return source
    pos = 0
    case_accepted = False
    while True:
        else_pos = source.find("else:", pos)
        else_if_pos = source.find("else if:", pos)
        pos = source.find("if:", pos)
        else_case = False
        first_case = True

        if us(else_if_pos) < us(pos):
            pos = else_if_pos
            first_case = False

        if us(else_pos) < us(pos):
            pos = else_pos
            else_case = True
            first_case = False

        if first_case:
            case_accepted = False

        if pos == -1:
            break

        if not else_case:
            conditions_start = source.find("(", pos)
            body_start = source.find("{", conditions_start) + 1
            conditions = source[conditions_start:body_start - 1]
            conditions = conditions.replace('\n', '')
            conditions = conditions.replace("&&", " and ")
            conditions = conditions.replace("||", " or ")
            conditions = conditions.replace("!", " not ")
        else:
            body_start = source.find("{", pos) + 1
            conditions = "True"

        gv = dict()
        for v in permutation:
            gv[str(v[0])] = v[1]

        conditional_block = ""

        i = body_start
        stack_size = 1
        while True:
            if source[i] == "{":
                stack_size += 1
            if source[i] == "}":
                stack_size -= 1
            if stack_size == 0:
                break
            i += 1

        if not case_accepted:
            try:
                if eval(conditions, gv):
                    conditional_block = source[body_start:i]
                    case_accepted = True
            except NameError:
                conditional_block = ""
        else:
            conditional_block = ""

        source = source.replace(source[pos:i+1], conditional_block)
        pos += len(conditional_block)

    return source


def replace_conditional_blocks(source):
    pos = 0
    while True:
        pos = source.find("if:", pos)
        if pos == -1:
            break
        conditions_start = source.find("(", pos)
        body_start = source.find("{", conditions_start) + 1
        conditions = source[conditions_start:body_start - 1]
        delimiters = [" ", "(", ")", "&", "|"]
        comparisons = [">", "<", "==", "!=", "<=", ">="]
        token = ""
        defined = ""
        for char in conditions:
            if char in delimiters:
                if char == " ":
                    continue
                if token != "":
                    ifdefined = True
                    for comp in comparisons:
                        if comp in token:
                            ifdefined = False
                    if ifdefined:
                        defined += "defined("
                        defined += token
                        defined += ")"
                    else:
                        defined += "("
                        defined += token
                        defined += ")"
                defined += char
                token = ""
            else:
                token += char
        i = body_start
        stack_size = 1
        while True:
            if source[i] == "{":
                stack_size += 1
            if source[i] == "}":
                stack_size -= 1
            if stack_size == 0:
                break
            i += 1

        conditional_block = "#if "
        conditional_block += defined + "\n"
        conditional_block += source[body_start:i]
        conditional_block += "#endif"

        source = source.replace(source[pos:i+1], conditional_block)
        pos = i
    return source


def strip_empty_vs_inputs(vs_input, vs_main):
    conditioned = vs_input.replace("\n", "").replace(";", "").replace(";", "").replace("}", "").replace("{", "")
    tokens = conditioned.split(" ")
    for t in tokens:
        if t == "":
            tokens.remove(t)
    if len(tokens) == 2:
        # input is empty so remove from vs_main args
        vs_input = ""
        name = tokens[1]
        pos = vs_main.find(name)
        prev_delim = max(us(vs_main[:pos].rfind(",")), us(vs_main[:pos].rfind("(")))
        next_delim = pos + min(us(vs_main[pos:].find(",")), us(vs_main[pos:].find(")")))
        vs_main = vs_main.replace(vs_main[prev_delim:next_delim], " ")
    return vs_input, vs_main


def create_vsc_psc(filename, shader_file_text, vs_name, ps_name, technique_name, permutation):
    mf = open(macros_file)
    macros_text = mf.read()
    mf.close()

    function_list = find_generic_functions(shader_file_text)

    #_find main ps and vs
    ps_main = ""
    vs_main = ""
    for func in function_list:
        ps_find_pos = func.find(ps_name)
        if ps_find_pos != -1:
            if func[ps_find_pos+len(ps_name)] == "(" and func[ps_find_pos-1] == " ":
                ps_main = func
        vs_find_pos = func.find(vs_name)
        if vs_find_pos != -1:
            if func[vs_find_pos+len(vs_name)] == "(" and func[vs_find_pos-1] == " ":
                vs_main = func

    # remove from generic function list
    function_list.remove(vs_main)
    if ps_main != "":
        if ps_main in function_list:
            function_list.remove(ps_main)

    vs_functions = ""
    vs_functions += find_used_functions(vs_main, function_list)

    ps_functions = ""
    if ps_main != "":
        ps_functions = find_used_functions(ps_main, function_list)

    global technique_defines
    macros_text += technique_defines

    vs_source = macros_text + "\n\n"
    ps_source = macros_text + "\n\n"

    vs_output_struct_name = vs_main[0:vs_main.find(" ")].strip()
    ps_output_struct_name = ps_main[0:ps_main.find(" ")].strip()

    vs_input_signature = vs_main[vs_main.find("(")+1:vs_main.find(")")].split(" ")

    vs_instance_input_struct_name = "null"
    vs_vertex_input_struct_name = "null"

    for i in range(0, len(vs_input_signature)):
        vs_input_signature[i] = vs_input_signature[i].replace(",", "")
        if vs_input_signature[i] == "_input" or vs_input_signature[i] == "input":
            vs_vertex_input_struct_name = vs_input_signature[i-1]
        elif vs_input_signature[i] == "_instance_input" or vs_input_signature[i] == "instance_input":
            vs_instance_input_struct_name = vs_input_signature[i-1]

    instance_input_source = find_struct(shader_file_text, "struct " + vs_instance_input_struct_name)
    vs_input_source = find_struct(shader_file_text, "struct " + vs_vertex_input_struct_name)

    # evaluate conditional inputs
    vs_input_source = evaluate_conditional_blocks(vs_input_source, permutation)
    instance_input_source = evaluate_conditional_blocks(instance_input_source, permutation)

    # remove empty inputs
    vs_input_source, vs_main = strip_empty_vs_inputs(vs_input_source, vs_main)
    instance_input_source, vs_main = strip_empty_vs_inputs(instance_input_source, vs_main)

    vs_output_source = find_struct(shader_file_text, "struct " + vs_output_struct_name)
    ps_output_source = find_struct(shader_file_text, "struct " + ps_output_struct_name)

    # constant / uniform buffers
    constant_buffers = find_constant_buffers(shader_file_text)

    # per technique cb
    global technique_cb_str
    if technique_cb_str != "":
        constant_buffers.append(technique_cb_str)

    # texture samplers
    texture_samplers_source = find_texture_samplers(shader_file_text)
    texture_samplers_source = evaluate_conditional_blocks(texture_samplers_source, permutation)

    # structs
    struct_list = find_struct_declarations(shader_file_text)

    # vertex shader
    for s in struct_list:
        vs_source += s
    vs_source += vs_input_source
    vs_source += instance_input_source
    vs_source += vs_output_source
    for cbuf in constant_buffers:
        vs_source += cbuf
    vs_source += texture_samplers_source
    vs_source += vs_functions
    vs_source += vs_main
    vs_source = evaluate_conditional_blocks(vs_source, permutation)

    # pixel shader
    for s in struct_list:
        ps_source += s
    ps_source += vs_output_source
    for cbuf in constant_buffers:
        ps_source += cbuf
    ps_source += ps_output_source
    ps_source += texture_samplers_source

    # allow null pixel shaders
    if ps_main != "":
        ps_source += ps_functions
        ps_source += ps_main
        ps_source = evaluate_conditional_blocks(ps_source, permutation)

    if shader_platform == "hlsl":
        compile_hlsl(vs_source, filename, "vs_4_0", ".vs", vs_name, technique_name)
        if ps_main != "":
            compile_hlsl(ps_source, filename, "ps_4_0", ".ps", ps_name, technique_name)
    elif shader_platform == "glsl":
        for s in struct_list:
            macros_text += s

        generate_glsl(
            filename, macros_text,
            vs_main, ps_main,
            vs_functions, ps_functions,
            vs_input_source, instance_input_source,
            vs_output_source, ps_output_source,
            constant_buffers, texture_samplers_source,
            technique_name, permutation)

    return make_input_info(vs_input_source), make_input_info(instance_input_source), make_input_info(vs_output_source)


def shader_compile_v1():
    print("compile shaders v1")
    for root, dirs, files in os.walk(shader_source_dir):
        for file in files:
            if file.endswith(".pmfx"):
                print("compiling: " + os.path.splitext(file_and_path)[0])
                file_and_path = os.path.join(root, file)
                create_shader_set(file_and_path, root)
                create_vsc_psc(file_and_path, "vs_main", "ps_main", "default", None)


def member_wise_merge(j1, j2):
    for key in j2.keys():
        if key not in j1.keys():
            j1[key] = j2[key]
        elif type(j1[key]) is dict:
            j1[key] = member_wise_merge(j1[key], j2[key])
    return j1


def inherit_technique(technique, pmfx_block):
    if "inherit" in technique.keys():
        inherit = technique["inherit"]
        if inherit in pmfx_block.keys():
            technique = member_wise_merge(technique, pmfx_block[inherit])
            # print(json.dumps(technique, indent=4))
    return technique


def get_permutation_conditionals(block, permutation):
    if "constants" in block:
        # find conditionals
        conditionals = []
        cblock = block["constants"]
        for key in cblock.keys():
            if key.find("permutation(") != -1:
                conditionals.append((key, cblock[key]))
        # check conditionals valid
        for c in conditionals:
            # remove conditional permutation
            del block["constants"][c[0]]

            full_condition = c[0].replace("permutation", "")
            full_condition = full_condition.replace("&&", "and")
            full_condition = full_condition.replace("||", "or")

            gv = dict()
            for v in permutation:
                gv[str(v[0])] = v[1]

            if eval(full_condition, gv):
                block["constants"] = member_wise_merge(block["constants"], c[1])
    return block


def generate_technique_texture_variables(pmfx_block, technique_name, permutation):
    global technique_texture
    technique_texture = []

    technique = pmfx_block[technique_name]
    if "texture_samplers" not in technique.keys():
        return

    textures = technique["texture_samplers"]

    get_permutation_conditionals(textures, permutation)

    for t in textures.keys():
        technique_texture.append((textures[t]["type"], t, textures[t]["unit"]))

    return


def generate_technique_constant_buffers(pmfx_block, technique_name, permutation, id):
    global technique_cb_str
    technique_cb_str = ""
    offset = 0
    constant_info = [["float", 1], ["float2", 2], ["float3", 3], ["float4", 4], ["float4x4", 16]]

    technique = pmfx_block[technique_name]
    technique_constants = [technique]

    # find inherited constants
    if "inherit_constants" in technique.keys():
        for inherit in technique["inherit_constants"]:
            technique_constants.append(pmfx_block[inherit])

    for tc in technique_constants:
        tc = get_permutation_conditionals(tc, permutation)

    # find all constants
    shader_constant = []
    shader_struct = []
    pmfx_constants = dict()

    for tc in technique_constants:
        if "constants" in tc.keys():
            # sort constants
            sorted_constants = []
            for const in tc["constants"]:
                for ci in constant_info:
                    if ci[0] == tc["constants"][const]["type"]:
                        cc = [const, ci[1]]
                        pos = 0
                        for sc in sorted_constants:
                            if cc[1] > sc[1]:
                                sorted_constants.insert(pos, cc)
                                break
                            pos += 1
                        if pos >= len(sorted_constants):
                            sorted_constants.append(cc)
            for const in sorted_constants:
                const_name = const[0]
                const_elems = const[1]
                pmfx_constants[const_name] = tc["constants"][const_name]
                pmfx_constants[const_name]["offset"] = offset
                pmfx_constants[const_name]["num_elements"] = const_elems
                shader_constant.append("\t" + tc["constants"][const_name]["type"] + " " + "m_" + const_name + ";\n")
                shader_struct.append("\t" + tc["constants"][const_name]["type"] + " " + "m_" + const_name + ";\n")
                offset += const_elems

    if offset == 0:
        return technique, ""

    # we must pad to 16 bytes alignment
    pre_pad_offset = offset
    diff = offset / 4
    next = math.ceil(diff)
    pad = (next - diff) * 4
    if pad != 0:
        shader_constant.append("\t" + constant_info[int(pad)][0] + " " + "m_padding" + ";\n")
        shader_struct.append("\t" + constant_info[int(pad)][0] + " " + "m_padding" + ";\n")

    offset += pad

    cb_str = "cbuffer material_data : register(b7)\n"
    cb_str += "{\n"
    for sc in shader_constant:
        cb_str += sc
    cb_str += "};\n"

    # append permutation string to shader c struct
    permutation_name = ""
    if int(id) != 0:
        for p in permutation:
            if p[1] == 1:
                permutation_name += "_" + p[0].lower()
            if p[1] > 1:
                permutation_name += "_" + p[0].lower() + p[1]

    c_struct = "struct " + technique_name + permutation_name + "\n"
    c_struct += "{\n"
    for ss in shader_struct:
        c_struct += ss
    c_struct += "};\n\n"

    # set for inserting into shader
    technique_cb_str = cb_str

    technique["constants"] = pmfx_constants
    technique["constants_used_bytes"] = int(pre_pad_offset * 4)
    technique["constants_size_bytes"] = int(offset * 4)

    assert int(offset * 4) % 16 == 0

    return technique, c_struct


def permute(define_list, permute_list, output_permutations):
    if len(define_list) == 0:
        output_permutations.append(list(permute_list))
    else:
        d = define_list.pop()
        for s in d[1]:
            ds = (d[0], s)
            permute_list.append(ds)
            output_permutations = permute(define_list, permute_list, output_permutations)
            if len(permute_list) > 0:
                permute_list.pop()
        define_list.append(d)
    return output_permutations


def generate_permutation_defines(permutation):
    global technique_defines
    technique_defines = ""
    for p in permutation:
        if p[1] == 0:
            continue
        technique_defines += "#define " + p[0] + " " + str(p[1]) + "\n"


def generate_permutation_id(define_list, permutation):
    pid = 0
    for p in permutation:
        for d in define_list:
            if p[0] == d[0]:
                if p[1] > 0:
                    exponent = d[2]
                    if exponent < 0:
                        continue
                    if p[1] > 1:
                        exponent = p[1]+exponent-1
                    pid += pow(2, exponent)
    return pid


def parse_pmfx(filename, root):
    file_and_path = os.path.join(root, filename)
    needs_building, shader_file_text, included_files = create_shader_set(file_and_path, root)
    if needs_building:
        # get shader code
        shader_c_struct = ""
        pmfx_loc = shader_file_text.find("pmfx:")
        if pmfx_loc == -1:
            if find_main(shader_file_text, "vs_main") == "":
                return
        json_loc = shader_file_text.find("{", pmfx_loc)
        techniques = []
        constant_buffers = find_constant_buffers(shader_file_text)
        texture_samplers_source = find_texture_samplers(shader_file_text)
        if pmfx_loc != -1:
            # find pmfx block
            pmfx_end = enclose_brackets(shader_file_text[pmfx_loc:])
            pmfx_block = json.loads(shader_file_text[json_loc:pmfx_end+json_loc])

            # inherit techniques
            for technique in pmfx_block:
                pmfx_block[technique] = inherit_technique(pmfx_block[technique], pmfx_block)

            # for technique for permutation generate and compile shader
            for technique in pmfx_block:
                technique_block = pmfx_block[technique]

                # permutation list
                output_permutations = []
                define_list = []
                permutation_options = dict()
                permutation_option_mask = 0

                if "permutations" in technique_block:
                    for p in technique_block["permutations"].keys():
                        pp = technique_block["permutations"][p]
                        define_list.append((p, pp[1], pp[0]))
                    if "defines" in technique_block.keys():
                        for d in technique_block["defines"]:
                            define_list.append((d, [1], -1))
                    output_permutations = permute(define_list, [], [])
                    for key in technique_block["permutations"]:
                        tp = technique_block["permutations"][key]
                        ptype = "checkbox"
                        if len(tp[1]) > 2:
                            ptype = "input_int"
                        permutation_options[key] = {"val": pow(2, tp[0]), "type": ptype}
                        mask = pow(2, tp[0])
                        permutation_option_mask += mask
                        shader_c_struct += "#define " + technique.upper() + "_" + key + " " + str(mask) + "\n"
                    del technique_block["permutations"]
                    shader_c_struct += "\n"

                # generate default permutation, inherit / get permutation constants
                technique_permutations = dict()
                tp = list(output_permutations)
                if len(tp) == 0:
                    default_permute = []
                    if "defines" in technique_block.keys():
                        for d in technique_block["defines"]:
                            default_permute.append((d, 1))
                    else:
                        default_permute = [("SINGLE_PERMUTATION", 1)]
                    tp.append(default_permute)
                technique_permutations[technique] = tp

                # fixes a bug where pmfx_block is written to during compile / shader generation
                src_pmfx = json.dumps(pmfx_block)

                for p in technique_permutations[technique]:
                    # names / permutation ids
                    technique_name = technique
                    id = 0
                    if p[0][0] != "SINGLE_PERMUTATION":
                        id = str(generate_permutation_id(define_list, p))
                        print("technique: " + technique + " [" + id + "] " + str(p))
                        if id != "0":
                            technique_name += "__" + id + "__"
                    else:
                        print("technique: " + technique)

                    # generate cbuffers, textures and c structs meta data / reflection
                    pmfx_block = json.loads(src_pmfx)
                    technique_json, c_stuct = generate_technique_constant_buffers(pmfx_block, technique, p, id)
                    generate_permutation_defines(p)
                    shader_c_struct += c_stuct
                    generate_technique_texture_variables(pmfx_block, technique, p)

                    # check for ps
                    ps_name = ""
                    if "ps" in technique_json.keys():
                        ps_name = technique_json["ps"]

                    # generate vs and ps
                    technique_json["name"] = technique
                    technique_json["vs_inputs"], \
                    technique_json["instance_inputs"], \
                    technique_json["vs_outputs"] = \
                    create_vsc_psc(file_and_path, shader_file_text, technique_json["vs"], ps_name, technique_name, p)

                    # permutation meta data
                    technique_json["permutations"] = permutation_options
                    technique_json["permutation_id"] = id
                    technique_json["permutation_option_mask"] = permutation_option_mask

                    # clean up ps
                    if "ps" in technique_json.keys():
                        del technique_json["ps"]
                        technique_json["ps_file"] = technique_name + ".psc"

                    # cleanup vs
                    del technique_json["vs"]
                    technique_json["vs_file"] = technique_name + ".vsc"
                    techniques.append(json.dumps(technique_json))
        else:
            # globals to insert into shaders
            global technique_defines
            technique_defines = ""
            global technique_cb_str
            technique_cb_str = ""
            default_technique = dict()
            default_technique["name"] = "default"
            default_technique["vs_file"] = "default.vsc"
            default_technique["ps_file"] = "default.psc"
            default_technique["vs_inputs"], \
                default_technique["instance_inputs"], \
                default_technique["vs_outputs"] =\
                create_vsc_psc(file_and_path, shader_file_text, "vs_main", "ps_main", "default", None)
            techniques.append(json.dumps(default_technique))

        # write out header file of c_structs for accessing materials in code
        if shader_c_struct != "":
            h_filename = filename.replace(".pmfx", ".h")
            if not os.path.exists("shader_structs"):
                os.mkdir("shader_structs")
            h_filename = os.path.join("shader_structs", h_filename)
            h_file = open(h_filename, "w+")
            h_file.write(shader_c_struct)
            h_file.close()

        # load json to dict
        tj = []
        for t in techniques:
            tj.append(json.loads(t))

        generate_shader_info(
            file_and_path,
            included_files,
            tj,
            texture_samplers_source,
            constant_buffers)


def shader_compile_pmfx():
    global error_code
    error_code = 0
    print("compile shaders pmfx")
    source_list = [pmtech_shaders, shader_source_dir]
    for source_dir in source_list:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                if file.endswith(".pmfx"):
                    parse_pmfx(file, root)


# build shaders
shader_compile_pmfx()

stats_end = time.time()
millis = int((stats_end - stats_start) * 1000)
print("Done (" + str(millis) + "ms)")



