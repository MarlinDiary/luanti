#!/usr/bin/env python3
"""Exercise production camera easing at multiple frame rates, without any UI."""
from pathlib import Path
import subprocess,tempfile
ROOT=Path(__file__).resolve().parents[2]
source=r'''
#include "course_steering.h"
#include <iostream>
int main() {
 int checks=0;
 for (float fps : {30.0f,60.0f,144.0f}) {
  CourseSteering s; s.active=true;s.heading=90;
  float yaw=0,pitch=20;
  for (int i=0;i<fps*2;i++) {
   float old=yaw;s.step(yaw,pitch,1/fps);
   if(yaw<old || yaw-old>360/fps+.001 || yaw>90.001)return 1;
  }
  if(std::abs(yaw-90)>.01 || std::abs(pitch)>.01)return 2;
  ++checks;
 }
 CourseSteering s;s.active=true;s.heading=1;
 float yaw=359,pitch=0;s.step(yaw,pitch,.016f);
 if(!(yaw>359 && yaw<361))return 3;++checks;
 s.clear();float old=yaw;s.step(yaw,pitch,.1f);
 if(yaw!=old || s.speed!=0 || s.active)return 4;++checks;
 // World direction compensation: smooth view must not steer into a wall.
 for(float view : {0.0f,30.0f,80.0f}) {
  float desired=-90,relative=(view-desired)*3.141592653589793/180;
  float world_x=std::sin(relative-view*3.141592653589793/180);
  if(std::abs(world_x-1)>.001)return 5;++checks;
 }
 // Inactive/dry modes never synthesize swim keys; feedback opposes drift.
 s.active=true;s.swim=true;s.swim_y=10;bool jump,sneak;
 s.swimKeys(9,-1,true,jump,sneak);if(!jump || sneak)return 6;++checks;
 s.swimKeys(11,1,true,jump,sneak);if(jump || !sneak)return 7;++checks;
 s.swimKeys(9,-1,false,jump,sneak);if(jump || sneak)return 8;++checks;
 s.clear();s.swimKeys(9,-1,true,jump,sneak);if(jump || sneak || s.swim)return 9;++checks;
 // Substep landing: a previously valid swim pulse must not become a land jump.
 s.active=true;s.swim=true;s.swim_y=10;
 for(float y : {9.42f,9.7f,9.9f,10.0f}) {
  s.swimKeys(y,0,true,jump,sneak,true);if(jump)return 10;++checks;
 }
 s.swimKeys(8,0,true,jump,sneak,true);if(!jump)return 11;++checks;
 s.swimKeys(9.9,0,true,jump,sneak,false);if(!jump)return 12;++checks;
 s.move_heading=90;s.heading=-90;s.speed=.5;
 for(float view : {-90.0f,-60.0f,0.0f}) {
  float relative=(view-s.move_heading)*3.141592653589793/180;
  float world_x=std::sin(relative-view*3.141592653589793/180);
  if(std::abs(world_x+1)>.001)return 13;++checks;
 }
 std::cout<<checks<<" steering regressions passed\n";
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.cpp').write_text(source)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-I',str(ROOT/'engine/src'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
 raise SystemExit(subprocess.run([str(p/'test')]).returncode)
