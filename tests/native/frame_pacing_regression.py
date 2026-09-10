#!/usr/bin/env python3
"""Compile actual frame limiter with a fake clock/window, without UI or sound."""
import argparse,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);a=p.parse_args()
s=a.source.read_text();start=s.index('void FpsControl::limit(');brace=s.index('{',start);end=brace+1;depth=1
while depth:
 depth+=(s[end]=='{')-(s[end]=='}');end+=1
method=s[start:end]
stub=r'''
#include <algorithm>
#include <cmath>
#include <string>
#include <iostream>
using f32=float;using u64=unsigned long long;
namespace porting { u64 now=1000000;u64 getTimeUs(){return now;}void preciseSleepUs(u64 us){now+=us;} }
struct IrrlichtDevice {bool focus=false;bool isWindowFocused(){return focus;}};
struct Settings {float getFloat(std::string n){return n=="fps_max"?60.0f:10.0f;}} settings,*g_settings=&settings;
struct FpsControl {u64 last_time=porting::now,busy_time=0,sleep_time=0;void limit(IrrlichtDevice*,f32*,bool=false);};
'''
main=r'''
int main(){IrrlichtDevice device;float dt;
 FpsControl idle;idle.limit(&device,&dt,false);if(std::abs(dt-.1f)>.001)return 1;
 FpsControl agent;agent.limit(&device,&dt,true);if(std::abs(dt-1/60.0f)>.001)return 2;
 device.focus=true;FpsControl manual;manual.limit(&device,&dt,false);if(std::abs(dt-1/60.0f)>.001)return 3;
 std::cout<<"3 frame pacing regressions passed\n";
}
'''
with tempfile.TemporaryDirectory() as tmp:
 path=Path(tmp);(path/'test.cpp').write_text(stub+method+main)
 subprocess.run(['c++','-std=c++17',str(path/'test.cpp'),'-o',str(path/'test')],check=True)
 raise SystemExit(subprocess.run([str(path/'test')]).returncode)
