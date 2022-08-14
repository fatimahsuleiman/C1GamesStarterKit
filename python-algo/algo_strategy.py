import gamelib
import random
import math
import warnings
from sys import maxsize
import json


"""
Most of the algo code you write will be in this file unless you create new
modules yourself. Start by modifying the 'on_turn' function.

Advanced strategy tips:

  - You can analyze action frames by modifying on_action_frame function

  - The GameState.map object can be manually manipulated to create hypothetical
  board states. Though, we recommended making a copy of the map to preserve
  the actual current map state.
"""

def are_in_range(loc_1, loc_2, range_):
    """
    Returns whether the two locations are in range of each other (Euclidean distance)
    """
    return (loc_1[0] - loc2[0])**2 + (loc_1[1] - loc2[1])**2 < range_**2
def are_in_range_one_to_multi(loc_1, locs_2, range_):
    return any(are_in_range(loc_1, loc, range) for loc in locs_2)
FRAMEDATA_PLAYER_ID_SELF = 1
FRAMEDATA_PLAYER_ID_ENEMY = 2

class AlgoStrategy(gamelib.AlgoCore):
    def __init__(self):
        super().__init__()
        seed = random.randrange(maxsize)
        random.seed(seed)
        gamelib.debug_write('Random seed: {}'.format(seed))

    def on_game_start(self, config):
        """
        Read in config and perform any initial setup here
        """
        gamelib.debug_write('Configuring your custom algo strategy...')
        self.config = config
        global WALL, SUPPORT, TURRET, SCOUT, DEMOLISHER, INTERCEPTOR, MP, SP
        WALL = config["unitInformation"][0]["shorthand"]
        SUPPORT = config["unitInformation"][1]["shorthand"]
        TURRET = config["unitInformation"][2]["shorthand"]
        SCOUT = config["unitInformation"][3]["shorthand"]
        DEMOLISHER = config["unitInformation"][4]["shorthand"]
        INTERCEPTOR = config["unitInformation"][5]["shorthand"]
        MP = 1
        SP = 0
        # This is a good place to do initial setup
        self.scored_on_locations = []
        self.scored_on_last_turn = []
        self.defences_by_column = [0 for i in range(28)]
        # (id, loc, type, total_damage, was_destroyed)
        self.own_structures_attacked = []

    def on_turn(self, turn_state):
        """
        This function is called every turn with the game state wrapper as
        an argument. The wrapper stores the state of the arena and has methods
        for querying its state, allocating your current resources as planned
        unit deployments, and transmitting your intended deployments to the
        game engine.
        """
        game_state = gamelib.GameState(self.config, turn_state)
        gamelib.debug_write('Performing turn {} of your custom algo strategy'.format(game_state.turn_number))
##        game_state.suppress_warnings(True)  #Comment or remove this line to enable warnings.

        self.our_strategy(game_state)

        game_state.submit_turn()

        #reset the variables that track damage on each turn
        self.own_structures_attacked = []
        self.scored_on_last_turn = []

    def our_strategy(self, game_state):
        #Only on the first turn
        if(game_state.turn_number == 0):
            self.initial_defences(game_state)
            self.initial_interceptors(game_state)
        else:
            self.rebuild_destroyed(game_state,self.get_enemy_attack_data(game_state)[1])
            if(game_state.turn_number < 3):
                self.upgrade_walls(game_state,game_state.get_resource(SP)/2)
                self.build_turrets(game_state)
                
            else:

            self.send_interceptors(game_state, self.check_defence(game_state))

    '''
    Utility function works out which quarter an x-coordinate is on
    '''
    @staticmethod
    def _x_to_quarter(x):
        return x // 7

    '''
    ////////////////
    FIND ENEMYS WEAKEST AREA OF DEFENCE
    ///////////////
    '''
    def find_weakest_area(self, game_state):
        # figuring out how weak the bottom left is
        location_options = []
        for x in range(15):
            for y in range(15, 22):
                location_options += [x, y]
        bottom_left_h = detect_area_weakness(game_state, location_options)

        # figuring out how weak the bottom right is
        location_options = []
        for x in range(15, 28):
            for y in range(15, 22):
                location_options += [x, y]
        bottom_right_h = detect_area_weakness(game_state, location_options)

        # figuring out how weak the top left is
        location_options = []
        for x in range(15):
            for y in range(22, 28):
                location_options += [x, y]
        top_left_h = detect_area_weakness(game_state, location_options)

        # figuring out how weak the top right is
        location_options = []
        for x in range(15, 28):
            for y in range(22, 28):
                location_options += [x, y]
        top_right_h = detect_area_weakness(game_state, location_options)

        d = {
            'tl': top_left_h,
            'tr': top_right_h,
            'br': bottom_right_h,
            'bl': bottom_left_h,
        }

        weakest = min(d, key=d.get)

        return weakest

    # Helper function for find_weakest_area, given a set of locations returns an indication of how strong that area is
    def detect_area_weakness(self, game_state, location_options):
        strength = 0
        for location in location_options:
            if game_state.contains_stationary_unit(location):
                for unit in game_state.game_map[location]:
                    strength += unit.health
        return strength

    # Function which finds path to edge and checks for defences on that path
    # The 'area' argument is designed to work with a given outut from find_weakest_area
    def find_path_and_defences(self, game_state, area, start_location):
        if area == 'tl':
            edge = game_state.game_map.TOP_LEFT
        elif area == 'tr':
            edge = game_state.game_map.TOP_RIGHT
        elif area == 'bl':
            edge = game_state.game_map.BOTTOM_LEFT
        else:
            edge = game_state.game_map.BOTTOM_RIGHT

        path = game_state.find_path_to_edge(start_location, edge)
        potential_attackers = []
        for location in path:
            attackers = game_state.get_attackers(location, 0)
            for attacker in attackers:
                potential_attackers += attacker

        return (path, potential_attackers)

    '''
    //////////////
    FIND WHERE ENEMY DID DAMAGE LAST TURN
    //////////////
    '''
    def get_enemy_attack_data(self, game_state):
        '''
        Gets info about what happened last turn. Returns:
        indices_of_attacked_quarters: [0, 1, 2, 3]
        destroyed_structures: [(x, y, structure_type), ...]
        damaged_structures: [(x, y), ...]
        edge_squares_reached  [(x, y), ...]
        '''
        quarters_attacked = []
        damage_in_quarter = [[0, 0], [0, 1], [0, 2], [0, 3]]
        damaged_structures = []
        destroyed_structures = []
        for struc in self.own_structures_attacked:
            loc = struc[1]
            unit_type = struc[2]
            hp_lost = struc[3]
            was_killed = struc[4]
            if was_killed:
                destroyed_structures.append((*loc, unit_type))
                defences_by_column[loc[0]] -= 1
            else:
                damaged_structures.append(loc)
            damage_in_quarter[self._x_to_quarter(loc[0])][0] += hp_lost
        edge_squares_reached = self.scored_on_last_turn
        for sq in edge_squares_reached:
            quarter = self._x_to_quarter(sq[0])
            if quarter not in quarters_attacked:
                quarters_attacked.append(quarter)
        damage_in_quarter.sort(reverse=True, key=lambda a:a[0])
        for a in damage_in_quarter:
            if a[0] and (a[1] not in quarters_attacked):
                quarters_attacked.append(a[1])
        return quarters_attacked, destroyed_structures, damaged_structures, edge_squares_reached

    """
    ///////
    INITIAL DEFENCE SETUP
    ///////
    """
    def initial_defences(self, game_state):
        """
        Build basic defenses using hardcoded locations.
        Remember to defend corners and avoid placing units in the front where enemy demolishers can attack them.
        """
        # Useful tool for setting up your base locations: https://www.kevinbai.design/terminal-map-maker
        # More community tools available at: https://terminal.c1games.com/rules#Download

        # Place turrets that attack enemy units
        turret_locations = [[6, 12], [11, 11], [16, 11], [21, 12]]
        # attempt_spawn will try to spawn units if we have resources, and will check if a blocking unit is already there
        game_state.attempt_spawn(TURRET, turret_locations)

        # Place walls in front of turrets to soak up damage for them
        wall_locations = [[0,13], [1,13], [2,13], [3,12], [4,12], [5,12], [6,13], [11,12], [16,12],
                          [21,13], [22,12], [23,12], [24,12], [25,13], [26,13], [27,13]]
        game_state.attempt_spawn(WALL, wall_locations)
        # Upgraded wall locations
        wall_upg_locations = [[6,13], [11,12], [16,12], [21,13]]
        # upgrade walls so they soak more damage
        game_state.attempt_upgrade(wall_upg_locations)

	#self.defences_by_columns contains the number of walls and turrets in each column
        #assume that on first turn, any turrets are placed behind walls so only need to look at walls
        for sq in wall_locations:
            self.defences_by_column[sq[0]] += 1

    """
    //////
    SENDS THE INITIAL INTERCEPTORS
    //////
    """
    def initial_interceptors(self, game_state):
        intr_loc = [[6,7],[21,7]]
        game_state.attempt_spawn(INTERCEPTOR, intr_loc)


    """
    //////
    CHECKS FOR THE WEAKEST DEFENCE
    //////
    """
    """
    def check_defence(self,game_state):
        #Turrets will only be placed on rows 11 to 13
        #Divides the map into four quarters and checks which quarter has the fewest turrets
        turret_num = [0,0,0,0]
        quarters = [[0,7],[7,14],[14,21],[21,28]]
        for i in range(len(quarters)):
            for j in range(quarters[i][0],quarters[i][1]):
                for h in range(11,14):
                    #Counts the number of turrets in each quarter
                    turret_num[i] += len(game_state.get_attackers([j,h],1))
        #Finds the quarter that has the least turrets
        min_quart = turret_num.index(min(turret_num))
        return(min_quart)
    """


    """
    //////
    SENDS INTERCEPTORS
    //////
    """
    def send_interceptors(self, game_state, min_quart):
        #List of spawn locations for interceptors
        friendly_edges = (game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_LEFT) +
                          game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_RIGHT))
        deploy_locations = self.filter_blocked_locations(friendly_edges, game_state)
        quarters = [[0,7],[7,14],[14,21],[21,28]]
        #Middle of the quarter
        mid_point = [(quarters[min_quart][0]+quarters[min_quart][1]-1)/2,12]
        #Finds the closest spawn point from the target
        distance = 100
        spawn_point = [0,0]
        for i in range(len(deploy_locations)):
            dist = game_state.game_map.distance_between_locations(deploy_locations[i],mid_point)
            if dist <= distance:
               spawn_point = deploy_locations[i]
               distance = dist
        #Spawns the interceptor at the closest spawn point
        game_state.attempt_spawn(INTERCEPTOR, spawn_point)


    """
    //////
    BUILDS DEFENCES
    //////
    """
    def rebuild_destroyed(self, game_state, destroyed_structures):
        #Rebuilds the destroyed structures
        for structure in destroyed_structures:
            if game_state.attempt_spawn(structure[2], (structure[0], structure[1]) ):
                self.defences_by_column[structure[0]] += 1

    def upgrade_walls(self, game_state, max_spend=None):
        #work out how many walls we can upgrade based on max spend
        #By default, spend at most half of available SP
        current_sp = game_state.get_resource(SP)
        if max_spend is None:
            max_spend = current_SP
        max_spend = min(max_spend, current_SP)
        number_to_upgrade = max_spend // game_state.type_cost(WALL, upgrade=True)[SP]

        #Upgrade the walls, going through the board based on the default
        # ordering of squares in GameMap
        for location in game_state.game_map:
            if game_state.contains_stationary_unit(location):
                for unit in game_state.game_map[location]:
                    if unit.player_index == 0 and unit.unit_type == WALL:
                        if game_state.attempt_upgrade(location):
                            number_to_upgrade -= 1
                    if not number_to_upgrade:
                        break
            if not number_to_upgrade:
                break

    def build_turrets(self, game_state,min_quart,max_spend=None):
        #work out how many to place based on how much SP we can spend
        current_SP = game_state.get_resource(SP)
        if max_spend is None:
            max_spend = current_SP
        max_spend = min(max_spend, current_SP)
        num_to_place = max_spend // game_state.type_cost(TURRET)[SP]

        #choose where to place them
        turret_locs = [
            [(2, 12), (4, 11), (5, 11)],
            [(8, 11), (9, 11), (11,11), (12,11)],
            [(15,11), (16,11), (18,11), (19,11)],
            [(23,11), (24,11), (25,12)],
        ]
        turret_locs = turret_locs[min_quart]

        #place as many as we can
        for loc in turret_locs:
            if game_state.attempt_spawn(TURRET, loc):
                num_to_place -= 1
                self.defences_by_column[loc[0]] += 1
            if not num_to_place:
                break

    '''
    /////////
    BUILD SUPPORTS
    //////////
    '''
    def place_supports(self, game_state, attack_path, max_spend=None):
        """
        Place supports (aka encryptors, shield units) to support an attack.
        attack_path: list of positions
        max_spend: maximum SP that can be spent in this function call
        """
        #assume supports only cost structure points and don't cost any mobile points
        #work out how many we can place
        current_SP = game_state.get_resource(SP)
        max_spend = min(current_SP, max_spend) if max_spend is not None else current_SP
        support_cost = game_state.type_cost(SUPPORT, upgrade=False)[SP]
        upgrade_cost = game_state.type_cost(SUPPORT, upgrade=True)[SP]
        shield_range = self.config["unitInformation"][UNIT_TYPE_TO_INDEX[SUPPORT]]["shieldRange"]
        upg_shield_range = self.config["unitInformation"][UNIT_TYPE_TO_INDEX[SUPPORT]]["upgrade"]["shieldRange"]
        num_to_place = max_spend // (support_cost + upgrade_cost)
        SP_left = max_spend - num_to_place * (support_cost + upgrade_cost)
        if support_cost < SP_left:
            num_to_place += 1
        #find where to place them
        # - prioritise placing them further forward
        # - make sure to place them where they can reach our units
        # - only place them where they are protected by a wall in the same column
        MAX_SUPPORT_Y = 10 #dont go too far forward
        path_squares_on_y = [[] for i in range(27)]
        for sq in attack_path:
            path_squares_on_y[sq[1]].append(sq)
        for y in range(MAX_SUPPORT_Y, -1, -1):
            x = path_squares_on_y[y][0][0]
            #try x+1, x-1, x+2, x-2, ...
            path_squares_in_range = []
            for row in path_squares_on_y[int(math.ceil(y-shield_range)) : int(y+shield_range)]:
                path_squares_in_range.extend(row)
            i = 1
            plus_in_range = minus_in_range = True
            while (plus_in_range or minus_in_range):
                sq = (x+i,y)
                if (plus_in_range
                        and defences_by_column[sq[0]] > 0
                        and sq not in path_squares_on_y[y]
                        and game_state.can_spawn(SUPPORT, sq)):
                    game_state.attempt_spawn(SUPPORT, sq)
                    game_state.attempt_upgrade(sq)
                    num_to_place -= 1
                if not num_to_place:
                    break
                sq = (x-i,y)
                if (minus_in_range
                        and defences_by_column[sq[0]] > 0
                        and sq not in path_squares_on_y[y]
                        and game_state.can_spawn(SUPPORT, sq)):
                    game_state.attempt_spawn(SUPPORT, sq)
                    game_state.attempt_upgrade(sq)
                    num_to_place -= 1
                if not num_to_place:
                    break
                i += 1
                plus_in_range  = are_in_range_one_to_multi((x+i,y), path_squares_in_range)
                minus_in_range = are_in_range_one_to_multi((x-i,y), path_squares_in_range)
            if not num_to_place:
                break

    """
    NOTE: All the methods after this point are part of the sample starter-algo
    strategy and can safely be replaced for your custom algo.
    """

    def starter_strategy(self, game_state):
        """
        For defence we will use a spread out layout and some interceptors early on.
        We will place turrets near locations the opponent managed to score on.
        For offense we will use long range demolishers if they place stationary units near the enemy's front.
        If there are no stationary units to attack in the front, we will send Scouts to try and score quickly.
        """
        # First, place basic defenses
        self.build_defences(game_state)
        # Now build reactive defences based on where the enemy scored
        self.build_reactive_defence(game_state)

        # If the turn is less than 5, stall with interceptors and wait to see enemy's base
        if game_state.turn_number < 5:
            self.stall_with_interceptors(game_state)
        else:
            # Now let's analyze the enemy base to see where their defenses are concentrated.
            # If they have many units in the front we can build a line for our demolishers to attack them at long range.
            if self.detect_enemy_unit(game_state, unit_type=None, valid_x=None, valid_y=[14, 15]) > 10:
                self.demolisher_line_strategy(game_state)
            else:
                # They don't have many units in the front so lets figure out their least defended area and send Scouts there.

                # Only spawn Scouts every other turn
                # Sending more at once is better since attacks can only hit a single scout at a time
                if game_state.turn_number % 2 == 1:
                    # To simplify we will just check sending them from back left and right
                    scout_spawn_location_options = [[13, 0], [14, 0]]
                    best_location = self.least_damage_spawn_location(game_state, scout_spawn_location_options)
                    game_state.attempt_spawn(SCOUT, best_location, 1000)

                # Lastly, if we have spare SP, let's build some supports
                support_locations = [[13, 2], [14, 2], [13, 3], [14, 3]]
                game_state.attempt_spawn(SUPPORT, support_locations)


    def build_reactive_defence(self, game_state):
        """
        This function builds reactive defences based on where the enemy scored on us from.
        We can track where the opponent scored by looking at events in action frames
        as shown in the on_action_frame function
        """
        for location in self.scored_on_locations:
            # Build turret one space above so that it doesn't block our own edge spawn locations
            build_location = [location[0], location[1]+1]
            game_state.attempt_spawn(TURRET, build_location)

    def stall_with_interceptors(self, game_state):
        """
        Send out interceptors at random locations to defend our base from enemy moving units.
        """
        # We can spawn moving units on our edges so a list of all our edge locations
        friendly_edges = (game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_LEFT)
                          + game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_RIGHT))

        # Remove locations that are blocked by our own structures
        # since we can't deploy units there.
        deploy_locations = self.filter_blocked_locations(friendly_edges, game_state)

        # While we have remaining MP to spend lets send out interceptors randomly.
        while game_state.get_resource(MP) >= game_state.type_cost(INTERCEPTOR)[MP] and len(deploy_locations) > 0:
            # Choose a random deploy location.
            deploy_index = random.randint(0, len(deploy_locations) - 1)
            deploy_location = deploy_locations[deploy_index]

            game_state.attempt_spawn(INTERCEPTOR, deploy_location)
            """
            We don't have to remove the location since multiple mobile
            units can occupy the same space.
            """

    def demolisher_line_strategy(self, game_state):
        """
        Build a line of the cheapest stationary unit so our demolisher can attack from long range.
        """
        # First let's figure out the cheapest unit
        # We could just check the game rules, but this demonstrates how to use the GameUnit class
        stationary_units = [WALL, TURRET, SUPPORT]
        cheapest_unit = WALL
        for unit in stationary_units:
            unit_class = gamelib.GameUnit(unit, game_state.config)
            if unit_class.cost[game_state.MP] < gamelib.GameUnit(cheapest_unit, game_state.config).cost[game_state.MP]:
                cheapest_unit = unit

        # Now let's build out a line of stationary units. This will prevent our demolisher from running into the enemy base.
        # Instead they will stay at the perfect distance to attack the front two rows of the enemy base.
        for x in range(27, 5, -1):
            game_state.attempt_spawn(cheapest_unit, [x, 11])

        # Now spawn demolishers next to the line
        # By asking attempt_spawn to spawn 1000 units, it will essentially spawn as many as we have resources for
        game_state.attempt_spawn(DEMOLISHER, [24, 10], 1000)

    def least_damage_spawn_location(self, game_state, location_options):
        """
        This function will help us guess which location is the safest to spawn moving units from.
        It gets the path the unit will take then checks locations on that path to
        estimate the path's damage risk.
        """
        damages = []
        # Get the damage estimate each path will take
        for location in location_options:
            path = game_state.find_path_to_edge(location)
            damage = 0
            for path_location in path:
                # Get number of enemy turrets that can attack each location and multiply by turret damage
                damage += len(game_state.get_attackers(path_location, 0)) * gamelib.GameUnit(TURRET, game_state.config).damage_i
            damages.append(damage)

        # Now just return the location that takes the least damage
        return location_options[damages.index(min(damages))]

    def detect_enemy_unit(self, game_state, unit_type=None, valid_x = None, valid_y = None):
        total_units = 0
        for location in game_state.game_map:
            if game_state.contains_stationary_unit(location):
                for unit in game_state.game_map[location]:
                    if (unit.player_index == 1
                        and (unit_type is None or unit.unit_type == unit_type)
                        and (valid_x is None or location[0] in valid_x)
                        and (valid_y is None or location[1] in valid_y)):
                        total_units += 1
        return total_units

    def filter_blocked_locations(self, locations, game_state):
        filtered = []
        for location in locations:
            if not game_state.contains_stationary_unit(location):
                filtered.append(location)
        return filtered

    def on_action_frame(self, turn_string):
        """
        This is the action frame of the game. This function could be called
        hundreds of times per turn and could slow the algo down so avoid putting slow code here.
        Processing the action frames is complicated so we only suggest it if you have time and experience.
        Full doc on format of a game frame at in json-docs.html in the root of the Starterkit.
        """
        # Let's record at what position we get scored on
        state = json.loads(turn_string)
        events = state["events"]
        for breach in events["breach"]:
            location = breach[0]
            owner = breach[4]
            # When parsing the frame data directly,
            # 1 is integer for yourself, 2 is opponent (StarterKit code uses 0, 1 as player_index instead)
            if owner == FRAMEDATA_PLAYER_ID_ENEMY:
                gamelib.debug_write("Got scored on at: {}".format(location))
                self.scored_on_locations.append(location)
                self.scored_on_last_turn.append(location)
        for damage_evt in events["damage"]:
            unit_type = damage_evt[2]
            owner = damage_evt[4]
            if owner == 1 and is_stationary(unit_type):
                loc = damage_evt[0]
                damage_hp = damage_evt[1]
                unit_id = damage_evt[3]
                unit_type_str = self.config["unitInformation"][unit_type]["shorthand"]
                found = False
                for struc in self.own_structures_attacked:
                    if struc[0] == unit_id:
                        struc[3] += damage_hp
                        found = True
                        break
                if not found:
                    self.own_structures_attacked.append([unit_id, loc, unit_type_str, damage_hp, False])
        for death_evt in events["death"]:
            unit_type = death_evt[1]
            owner = death_evt[3]
            was_intentional = death_evt[4]
            if owner == 1 and is_stationary(unit_type) and not was_intentional:
                loc = death_evt[0]
                unit_id = death_evt[2]
                found = False
                for struc in self.own_structures_attacked:
                    if struc[0] == unit_id:
                        struc[4] = True
                        found = True
                        break
                if not found:
                    #I dont yet know if a damage event is emitted if a structure is shot to death.
                    #the code assumes so, so leaving this in until testing.
                    gamelib.debug_write('Structure was maliciously destroyed but not damaged '+
                                        str(death_evt))



if __name__ == "__main__":
    algo = AlgoStrategy()
    algo.start()
