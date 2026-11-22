"""worker 子进程也会导入的部分：不导入 ``app.*`` 和 ``auto_mas_core``。

子包 ``agent_env``、``runtime_pool`` 保持宿主原来的目录层次，包内相对导入不变。
"""
