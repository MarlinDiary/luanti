#!/usr/bin/env python3
"""Compile the production respawn branch; modern death forms need their handler."""
import argparse,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);a=p.parse_args()
s=a.source.read_text();start=s.index('} else if (op == "respawn") {')+len('} else if (op == "respawn") {');end=s.index('} else {',start);body=s[start:end]
source='''#include <stdexcept>
#include <iostream>
struct Player { bool dead; bool isDead(){return dead;} };
struct Client { int legacy=0; void sendRespawnLegacy(){legacy++;} };
struct Form {int id=0,closed=0;int courseFormId(){return id;} void courseClose(){closed++;}};
void courseRelease(bool) {}
void respawn(Player *player,Client *client,Form &m_game_formspec) {'''+body+'''}
int main(){
 Player p{true};Client c;Form f;f.id=1;respawn(&p,&c,f);
 if(f.closed!=1 || c.legacy){std::cout<<"FAIL modern death form did not receive its normal close handler\\n";return 1;}
 f.id=0;respawn(&p,&c,f);if(c.legacy!=1)return 2;
 p.dead=false;try{respawn(&p,&c,f);return 3;}catch(const std::runtime_error&){}
 std::cout<<"PASS modern formspec, legacy fallback, live-player guard\\n";
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.cpp').write_text(source);subprocess.run(['c++','-std=c++17',str(p/'test.cpp'),'-o',str(p/'test')],check=True);raise SystemExit(subprocess.run([str(p/'test')]).returncode)
