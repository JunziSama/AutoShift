import ctypes as c
import _tkinter
print("Tkinter extension:", _tkinter.__file__)
dll = c.CDLL("tcl86t.dll")
dll.Tcl_CreateInterp.restype = c.c_void_p
dll.Tcl_Init.argtypes = [c.c_void_p]
dll.Tcl_Init.restype = c.c_int
dll.Tcl_GetStringResult.argtypes = [c.c_void_p]
dll.Tcl_GetStringResult.restype = c.c_char_p
dll.Tcl_Eval.argtypes = [c.c_void_p, c.c_char_p]
interp = dll.Tcl_CreateInterp()
dll.Tcl_Eval(interp, b"info patchlevel")
print("Tcl DLL version:", dll.Tcl_GetStringResult(interp).decode())
print("Tcl_Init return:", dll.Tcl_Init(interp))
print("Tcl_Init detail:", dll.Tcl_GetStringResult(interp).decode(errors="replace"))
